"""Upload model GLBs to R2 under weapons/models/ (incremental by size).
Creds: MODELS_* env vars or R2_ENV=<path to r2.env>."""
import os
import sys

MODELS = r"A:\bf6weapons\models"
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
    have = {}
    tok = None
    while True:
        kw = dict(Bucket=bucket, Prefix=PREFIX, MaxKeys=1000)
        if tok:
            kw["ContinuationToken"] = tok
        r = cl.list_objects_v2(**kw)
        for o in r.get("Contents", []):
            have[o["Key"]] = o["Size"]
        if not r.get("IsTruncated"):
            break
        tok = r.get("NextContinuationToken")
    print("bucket has %d model objects" % len(have))

    up = skip = 0
    for f in sorted(os.listdir(MODELS)):
        if not f.endswith(".glb"):
            continue
        p = os.path.join(MODELS, f)
        key = PREFIX + f
        sz = os.path.getsize(p)
        if have.get(key) == sz:
            skip += 1
            continue
        cl.upload_file(p, bucket, key,
                       ExtraArgs={"ContentType": "model/gltf-binary"})
        up += 1
        if up % 25 == 0:
            print("uploaded %d (skipped %d)..." % (up, skip), flush=True)
    print("DONE uploaded=%d skipped=%d" % (up, skip))


if __name__ == "__main__":
    main()
