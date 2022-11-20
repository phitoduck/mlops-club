import os
from aws_cdk import App, Environment
from cdk_metaflow.main import MetaflowStack
from cdk_metaflow.config import MetaflowStackConfig

# for development, use account/region from cdk cli
DEV_ENV = Environment(account=os.getenv("CDK_DEFAULT_ACCOUNT"), region=os.getenv("CDK_DEFAULT_REGION"))

CONFIG = MetaflowStackConfig()
APP = App()

MetaflowStack(APP, "awscdk-metaflow-dev", config=CONFIG, env=DEV_ENV)

APP.synth()
