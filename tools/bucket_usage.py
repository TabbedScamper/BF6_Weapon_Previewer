"""Report R2 bucket usage by top-level prefix + estimated monthly storage cost.
Creds: MODELS_* env vars or R2_ENV=<path to r2.env>."""
import os
import sys
from collections import defaultdict


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


load_env()
import boto3

cl = boto3.client(
    "s3",
    endpoint_url=os.environ["MODELS_ENDPOINT"],
    aws_access_key_id=os.environ["MODELS_KEY_ID"],
    aws_secret_access_key=os.environ["MODELS_SECRET"],
)
bucket = os.environ["MODELS_BUCKET"]

sizes = defaultdict(int)
counts = defaultdict(int)
tok = None
total = 0
n = 0
while True:
    kw = dict(Bucket=bucket, MaxKeys=1000)
    if tok:
        kw["ContinuationToken"] = tok
    r = cl.list_objects_v2(**kw)
    for o in r.get("Contents", []):
        pre = o["Key"].split("/", 1)[0] if "/" in o["Key"] else "(root)"
        sizes[pre] += o["Size"]
        counts[pre] += 1
        total += o["Size"]
        n += 1
    if not r.get("IsTruncated"):
        break
    tok = r.get("NextContinuationToken")

print("bucket: %s   objects: %d   total: %.2f GB" % (bucket, n, total / 1e9))
print("%-24s %10s %12s" % ("prefix", "objects", "size"))
for pre in sorted(sizes, key=lambda p: -sizes[p]):
    print("%-24s %10d %11.2f GB" % (pre + "/", counts[pre], sizes[pre] / 1e9))

gb_month = total / 1e9
free = 10.0
billable = max(0.0, gb_month - free)
print()
print("R2 pricing: storage $0.015/GB-month (first 10 GB free), egress FREE,")
print("Class A ops $4.50/M (first 1M free), Class B $0.36/M (first 10M free).")
print("Estimated storage cost: %.1f GB stored -> $%.2f/month (%.1f GB over free tier)"
      % (gb_month, billable * 0.015, billable))
