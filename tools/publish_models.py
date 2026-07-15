"""Optimize + upload weapon GLBs to the shared R2 bucket under weapons/models/.

Incremental and resume-able:
  raw A:\\bf6weapons\\models\\*.glb --(gltf-transform draco+webp)--> A:\\bf6weapons\\web\\
  A:\\bf6weapons\\web\\*.glb --(missing/size-changed only)--> r2://<bucket>/weapons/models/

Credentials: MODELS_ENDPOINT/MODELS_BUCKET/MODELS_KEY_ID/MODELS_SECRET env vars,
or an r2.env file (KEY=VALUE lines) whose path is given by R2_ENV.

Usage: publish_models.py [--loop]     (--loop: keep polling while the mesh
                                       conversion batch is still producing)
"""
import os
import subprocess
import sys
import time

RAW = r"A:\bf6weapons\models"
WEB = r"A:\bf6weapons\web"
GT = r"A:\bf6weapons\gt\node_modules\.bin\gltf-transform.cmd"
PREFIX = "weapons/models/"


def load_env():
    if "MODELS_ENDPOINT" in os.environ:
        return
    envfile = os.environ.get("R2_ENV")
    if not envfile or not os.path.exists(envfile):
        sys.exit("set MODELS_* env vars or R2_ENV=<path to r2.env>")
    for ln in open(envfile):
        if "=" in ln:
            k, v = ln.strip().split("=", 1)
            os.environ.setdefault(k, v)


def _optimize_one(f):
    src = os.path.join(RAW, f)
    dst = os.path.join(WEB, f)
    r = subprocess.run(
        [GT, "optimize", src, dst, "--compress", "draco", "--texture-compress", "webp"],
        capture_output=True, text=True, timeout=900,
    )
    if r.returncode != 0 or not os.path.exists(dst):
        return "OPTIMIZE FAIL %s: %s" % (f, (r.stderr or r.stdout)[-300:])
    return None


def optimize_pass():
    from concurrent.futures import ThreadPoolExecutor

    os.makedirs(WEB, exist_ok=True)
    todo = []
    for f in sorted(os.listdir(RAW)):
        if not f.endswith(".glb"):
            continue
        dst = os.path.join(WEB, f)
        src = os.path.join(RAW, f)
        if os.path.exists(dst) and os.path.getmtime(dst) >= os.path.getmtime(src):
            continue
        todo.append(f)
    done = fail = 0
    with ThreadPoolExecutor(max_workers=6) as ex:
        for err in ex.map(_optimize_one, todo):
            if err:
                print(err, flush=True)
                fail += 1
            else:
                done += 1
                if done % 25 == 0:
                    print("optimized %d/%d..." % (done, len(todo)), flush=True)
    return done, fail


def bucket_listing(cl, bucket):
    keys = {}
    tok = None
    while True:
        kw = dict(Bucket=bucket, Prefix=PREFIX, MaxKeys=1000)
        if tok:
            kw["ContinuationToken"] = tok
        r = cl.list_objects_v2(**kw)
        for o in r.get("Contents", []):
            keys[o["Key"]] = o["Size"]
        if not r.get("IsTruncated"):
            return keys
        tok = r.get("NextContinuationToken")


def upload_pass(cl, bucket, have):
    up = skip = 0
    for f in sorted(os.listdir(WEB)):
        if not f.endswith(".glb"):
            continue
        p = os.path.join(WEB, f)
        key = PREFIX + f
        sz = os.path.getsize(p)
        if have.get(key) == sz:
            skip += 1
            continue
        cl.upload_file(p, bucket, key, ExtraArgs={
            "ContentType": "model/gltf-binary",
            "CacheControl": "public, max-age=31536000, immutable",
        })
        have[key] = sz
        up += 1
        if up % 20 == 0:
            print("uploaded %d..." % up, flush=True)
    return up, skip


def main():
    load_env()
    import boto3

    cl = boto3.client(
        "s3",
        endpoint_url=os.environ["MODELS_ENDPOINT"],
        aws_access_key_id=os.environ["MODELS_KEY_ID"],
        aws_secret_access_key=os.environ["MODELS_SECRET"],
    )
    bucket = os.environ["MODELS_BUCKET"]
    have = bucket_listing(cl, bucket)
    print("bucket already has %d objects under %s" % (len(have), PREFIX), flush=True)

    loop = "--loop" in sys.argv
    idle = 0
    while True:
        od, of = optimize_pass()
        up, sk = upload_pass(cl, bucket, have)
        print("pass: optimized %d (fail %d), uploaded %d, up-to-date %d" % (od, of, up, sk), flush=True)
        if not loop:
            break
        if od == 0 and up == 0:
            idle += 1
            if idle >= 8:          # ~16 quiet minutes = conversion finished
                break
        else:
            idle = 0
        time.sleep(120)
    total = sum(os.path.getsize(os.path.join(WEB, f)) for f in os.listdir(WEB) if f.endswith(".glb"))
    print("DONE. optimized store: %.2f GB in %s" % (total / 1e9, WEB))


if __name__ == "__main__":
    main()
