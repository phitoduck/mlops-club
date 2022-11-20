import os
from aws_cdk import App, Environment, Stack
import aws_cdk.cloudformation_include as cfn_include
from pathlib import Path

THIS_DIR = Path(__file__).parent
TEMPLATE_FPATH = THIS_DIR / "./cdk_metaflow/official-metaflow-template.yml"

# for development, use account/region from cdk cli
os.environ["AWS_PROFILE"] = "mlops-club"
DEV_ENV = Environment(account=os.getenv("CDK_DEFAULT_ACCOUNT"), region=os.getenv("CDK_DEFAULT_REGION"))

APP = App()

class OfficialMetaflowStack(Stack):
    def __init__(self, scope: App, id: str, **kwargs):
        super().__init__(scope, id, **kwargs)
        cfn_include.CfnInclude(
            self, 
            "official-metaflow-template", 
            template_file=str(TEMPLATE_FPATH),
            parameters={"EnableUI": "true"},
        )

OfficialMetaflowStack(APP, "official-metaflow-stack")

APP.synth()
