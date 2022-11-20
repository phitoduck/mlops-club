import os
from aws_cdk import App, Environment
from cdk_metaflow.main import MetaflowStack
from cdk_metaflow.config import MetaflowStackConfig
from functools import lru_cache
import boto3

# for development, use account/region from cdk cli

DEV_ENV = Environment(account=os.environ["AWS_ACCOUNT_ID"], region=os.getenv("AWS_REGION"))

CONFIG = MetaflowStackConfig()
APP = App()

MetaflowStack(APP, "awscdk-metaflow-dev", config=CONFIG, env=DEV_ENV)

APP.synth()
