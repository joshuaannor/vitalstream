"""Shared helpers for the AWS scripts: read the deployed stack's outputs."""

import boto3

STACK_NAME = "vitalstream"
REGION = "us-east-1"


def session() -> boto3.Session:
    return boto3.Session(region_name=REGION)


def stack_outputs(sess: boto3.Session, stack_name: str = STACK_NAME) -> dict[str, str]:
    """{'RawBucketName': ..., 'CuratedBucketName': ..., ...} from CloudFormation."""
    cfn = sess.client("cloudformation")
    stack = cfn.describe_stacks(StackName=stack_name)["Stacks"][0]
    return {o["OutputKey"]: o["OutputValue"] for o in stack.get("Outputs", [])}
