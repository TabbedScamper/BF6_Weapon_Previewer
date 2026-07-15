"""Upload the skin texture library to R2 under weapons/skins/ (incremental).
Creds: MODELS_* env vars or R2_ENV=<path to r2.env>."""
import os
import sys

SKINS = r"A:\bf6weapons\skins"
PREFIX = "weapons/skins/"


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
    print("bucket has %d skin objects" % len(have))

    up = skip = 0
    for dirpath, _dirs, files in os.walk(SKINS):
        for f in files:
            if not f.endswith(".webp"):
                continue
            p = os.path.join(dirpath, f)
            rel = os.path.relpath(p, SKINS).replace(os.sep, "/")
            key = PREFIX + rel
            if have.get(key) == os.path.getsize(p):
                skip += 1
                continue
            cl.upload_file(p, bucket, key, ExtraArgs={
                "ContentType": "image/webp",
                "CacheControl": "public, max-age=31536000, immutable",
            })
            up += 1
            if up % 100 == 0:
                print("uploaded %d..." % up, flush=True)
    print("DONE uploaded=%d up-to-date=%d" % (up, skip))


if __name__ == "__main__":
    main()
