"""Remove everything VitalStream created in AWS, so nothing keeps costing money.

CloudFormation can't delete buckets that still hold files, so this script:
  1. permanently deletes every object version in the raw, curated and trail buckets
  2. deletes the Glue databases that the Athena DDL created (not part of the stack)
  3. deletes the CloudFormation stack (buckets, Lambda, role, alarms, workgroup, trail)

THIS CANNOT BE UNDONE. The data is synthetic and can be re-generated, but the
CloudTrail logs in the trail bucket are gone for good.

Usage (from the repo root, venv active):
    python scripts/teardown.py
"""

import sys

from botocore.exceptions import ClientError

from stack import STACK_NAME, session, stack_outputs

GLUE_DATABASES = ("vitalstream_gold", "vitalstream_silver")


def empty_bucket(s3, bucket: str) -> int:
    """Delete every version and delete marker (needed for versioned buckets)."""
    deleted = 0
    for page in s3.get_paginator("list_object_versions").paginate(Bucket=bucket):
        items = page.get("Versions", []) + page.get("DeleteMarkers", [])
        objects = [{"Key": v["Key"], "VersionId": v["VersionId"]} for v in items]
        for i in range(0, len(objects), 1000):
            s3.delete_objects(Bucket=bucket, Delete={"Objects": objects[i:i + 1000], "Quiet": True})
        deleted += len(objects)
    return deleted


def main() -> int:
    sess = session()
    try:
        out = stack_outputs(sess)
    except ClientError as exc:
        print(f"Stack {STACK_NAME!r} not found ({exc.response['Error']['Code']}). Nothing to do.")
        return 0

    buckets = [out[k] for k in ("RawBucketName", "CuratedBucketName", "TrailBucketName") if k in out]
    print(f"This permanently deletes stack {STACK_NAME!r}, the Glue databases {', '.join(GLUE_DATABASES)}")
    print("and every file in:")
    for b in buckets:
        print(f"  s3://{b}")
    if input(f"Type the stack name ({STACK_NAME}) to confirm: ").strip() != STACK_NAME:
        print("Cancelled. Nothing was deleted.")
        return 1

    s3 = sess.client("s3")
    for b in buckets:
        print(f"Emptying s3://{b} ... {empty_bucket(s3, b)} object versions deleted")

    glue = sess.client("glue")
    for db in GLUE_DATABASES:
        try:
            glue.delete_database(Name=db)  # also deletes its tables and views
            print(f"Deleted Glue database {db}")
        except glue.exceptions.EntityNotFoundException:
            print(f"Glue database {db} not found (already gone)")

    cfn = sess.client("cloudformation")
    print(f"Deleting stack {STACK_NAME} (takes 1-3 minutes) ...")
    cfn.delete_stack(StackName=STACK_NAME)
    cfn.get_waiter("stack_delete_complete").wait(StackName=STACK_NAME)
    print("Stack deleted.")
    print("SAM's own artifact stack 'aws-sam-cli-managed-default' (a small S3 bucket) is left in place;")
    print("it costs fractions of a cent. Remove it in the CloudFormation console if you want a fully empty account.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
