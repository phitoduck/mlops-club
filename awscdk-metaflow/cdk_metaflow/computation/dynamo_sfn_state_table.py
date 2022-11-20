from constructs import Construct
import aws_cdk.aws_dynamodb as dynamodb

from cdk_metaflow.utils import make_namer_fn, TNamerFn

def make_step_function_state_ddb_table(
    scope: Construct, id_prefix: str
) -> dynamodb.Table:
    """
    Create a DynamoDB table used to store information/state of Metaflow Flow runs when using step functions.

    ```yaml
    StepFunctionsStateDDB:
        Type: AWS::DynamoDB::Table
        Properties:
            BillingMode: PAY_PER_REQUEST
            AttributeDefinitions:
                - AttributeName: "pathspec"
                    AttributeType: "S"
            KeySchema:
                - AttributeName: "pathspec"
                    KeyType: "HASH"
            TimeToLiveSpecification:
                AttributeName: ttl
                Enabled: true
    ```
    """
    make_id: TNamerFn = make_namer_fn(id_prefix)
    sfn_state_table = dynamodb.Table(
        scope=scope,
        id=make_id("metaflow-sfn-state-ddb-table"),
        billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
        partition_key=dynamodb.Attribute(
            name="pathspec", type=dynamodb.AttributeType.STRING
        ),
        time_to_live_attribute="ttl",
    )
    return sfn_state_table