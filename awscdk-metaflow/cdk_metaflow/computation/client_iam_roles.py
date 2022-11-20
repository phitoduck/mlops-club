from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_dynamodb as dynamodb
from constructs import Construct
from aws_cdk import Stack

from typing import Optional

from cdk_metaflow.utils import make_namer_fn, TNamerFn


def make_ecs_s3_access_iam_role(
    scope: Construct,
    id_prefix: str,
    artifacts_bucket_name: str,
    flow_run_state_ddb_table_name: str,
    allow_sagemaker: Optional[bool] = False,
) -> iam.Role:
    """
    From the

    METAFLOW_ECS_S3_ACCESS_IAM_ROLE

    The metaflow client needs these permissions to run. This is the role
    that the ECS tasks assume as the AWS Batch jobs run.

    Summary:
    - read/write from the artifacts bucket
    - read/write the dynamodb table holding info about the state machine / flow state
    - put log events in CloudWatch
    - create/invoke sagemaker endpoints?

    This role isn't directly associated with the compute cluster or ECS tasks. Instead,
    I think that the metaflow SDK running in the batch job reaches out and assumes this role.

    ```yaml
    BatchS3TaskRole:
        Type: AWS::IAM::Role
        Properties:
            AssumeRolePolicyDocument:
                Version: '2012-10-17'
                Statement:
                Effect: Allow
                Principal:
                    Service:
                    - ecs-tasks.amazonaws.com
                Action:
                    - sts:AssumeRole

    # NOTE: '/' is actually IAM's default value for this parameter
    Path: /

    # NOTE: This allowed CloudFormation template users to add permissions to the ECS batch workers; this seems unnecessary with CDK so we're leaving it out
    ManagedPolicyArns:
        - !If
        - EnableAddtionalWorkerPolicy
        - !Ref 'AdditionalWorkerPolicyArn'
        - !Ref AWS::NoValue

    Policies:
        - PolicyName: CustomS3ListBatch
        PolicyDocument:
            Version: '2012-10-17'
            Statement:
            Sid: BucketAccessBatch
            Effect: Allow
            Action: s3:ListBucket
            Resource: !GetAtt 'MetaflowS3Bucket.Arn'
        - PolicyName: CustomS3Batch
        PolicyDocument:
            Version: '2012-10-17'
            Statement:
            Sid: ObjectAccessBatch
            Effect: Allow
            Action:
                - s3:PutObject
                - s3:GetObject
                - s3:DeleteObject
            Resource: !Join ['', [ !GetAtt 'MetaflowS3Bucket.Arn', '/*' ]]
        - PolicyName: DenyPresignedBatch
        PolicyDocument:
            Version: '2012-10-17'
            Statement:
            Sid: DenyPresignedBatch
            Effect: Deny
            Action: s3:*
            Resource: '*'
            Condition:
                StringNotEquals:
                s3:authType: REST-HEADER
        - PolicyName: AllowSagemaker
        PolicyDocument:
            Version: '2012-10-17'
            Statement:
            - Sid: AllowSagemakerCreate
            Effect: Allow
            Action: sagemaker:CreateTrainingJob
            Resource: !Sub arn:${IAMPartition}:sagemaker:${AWS::Region}:${AWS::AccountId}:training-job/*
            - Sid: AllowSagemakerDescribe
            Effect: Allow
            Action: sagemaker:DescribeTrainingJob
            Resource: !Sub arn:${IAMPartition}:sagemaker:${AWS::Region}:${AWS::AccountId}:training-job/*
            - Sid: AllowSagemakerDeploy
            Effect: Allow
            Action:
                - "sagemaker:CreateModel"
                - "sagemaker:CreateEndpointConfig"
                - "sagemaker:CreateEndpoint"
                - "sagemaker:DescribeModel"
                - "sagemaker:DescribeEndpoint"
                - "sagemaker:InvokeEndpoint"
            Resource:
                - !Sub "arn:${IAMPartition}:sagemaker:${AWS::Region}:${AWS::AccountId}:endpoint/*"
                - !Sub "arn:${IAMPartition}:sagemaker:${AWS::Region}:${AWS::AccountId}:model/*"
                - !Sub "arn:${IAMPartition}:sagemaker:${AWS::Region}:${AWS::AccountId}:endpoint-config/*"
        - PolicyName: IAM_PASS_ROLE
        PolicyDocument:
            Version: '2012-10-17'
            Statement:
            Sid: AllowPassRole
            Effect: Allow
            Action: iam:PassRole
            Resource: '*'
            Condition:
                StringEquals:
                iam:PassedToService: sagemaker.amazonaws.com
        - PolicyName: DynamoDB
        PolicyDocument:
            Version: '2012-10-17'
            Statement:
            - Sid: Items
            Effect: Allow
            Action:
                - "dynamodb:PutItem"
                - "dynamodb:GetItem"
                - "dynamodb:UpdateItem"
            Resource: !Sub arn:${IAMPartition}:dynamodb:${AWS::Region}:${AWS::AccountId}:table/${StepFunctionsStateDDB}
        - PolicyName: Cloudwatch
        PolicyDocument:
            Version: '2012-10-17'
            Statement:
            - Sid: AllowPutLogs
            Effect: Allow
            Action:
                - 'logs:CreateLogStream'
                - 'logs:PutLogEvents'
            Resource: '*'
    ```
    """
    make_id: TNamerFn = make_namer_fn(id_prefix)

    ecs_s3_access_role = iam.Role(
        scope,
        id=make_id("ecs_s3_access_role"),
        assumed_by=iam.ServicePrincipal(service="ecs-tasks.amazonaws.com"),
    )

    # access to artifacts bucket
    artifacts_bucket = s3.Bucket.from_bucket_name(
        scope=scope, id=make_id("artifacts-bucket-for-iam"), bucket_name=artifacts_bucket_name
    )
    artifacts_bucket.grant_read_write(ecs_s3_access_role, objects_key_pattern="*")

    # access to step functions state dynamo table
    sfn_metaflow_state_dynamo_table = dynamodb.Table.from_table_name(
        scope=scope,
        id=make_id("sfn-metaflow-state-tbl"),
        table_name=flow_run_state_ddb_table_name,
    )
    sfn_metaflow_state_dynamo_table.grant_read_write_data(ecs_s3_access_role)

    policies_to_attach = [
        # ???
        make_deny_presigned_batch_policy(scope=scope, id_prefix=id_prefix),
        # access to push logs in CloudWatch
        make__allow_put_cloudwatch_logs__policy(scope=scope, id_prefix=id_prefix),
    ]

    # access to deploy to sagemaker
    if allow_sagemaker:
        policies_to_attach += [
            make_allow_sagemaker_policy(scope=scope, id_prefix=id_prefix),
            make__allow_pass_role_to_sagemaker_service__policy(
                scope=scope, id_prefix=id_prefix
            ),
        ]

    for policy in policies_to_attach:
        ecs_s3_access_role.attach_inline_policy(policy=policy)

    return ecs_s3_access_role


def make_deny_presigned_batch_policy(scope: Construct, id_prefix: str) -> iam.Policy:
    """
    TODO: What is this for?

    ```yaml
    PolicyName: DenyPresignedBatch
    PolicyDocument:
        Version: '2012-10-17'
        Statement:
            Sid: DenyPresignedBatch
            Effect: Deny
            Action: s3:*
            Resource: '*'
            Condition:
                StringNotEquals:
                    s3:authType: REST-HEADER
    ```
    """
    make_id: TNamerFn = make_namer_fn(id_prefix)
    policy_stmt = iam.PolicyStatement(
        actions=["s3:*"], effect=iam.Effect.DENY, resources=["*"]
    )
    policy_stmt.add_condition("StringNotEquals", {"s3:authType": "REST-HEADER"})
    deny_presigned_batch_policy = iam.Policy(
        scope=scope,
        id=make_id("deny-presigned-batch"),
        document=iam.PolicyDocument(statements=[policy_stmt]),
    )
    return deny_presigned_batch_policy


def make_allow_sagemaker_policy(scope: Construct, id_prefix: str) -> iam.Policy:
    """
    TODO: what is this for? Can Metaflow deploy models as SageMaker endpoints?

    ```yaml
    PolicyName: AllowSagemaker
    PolicyDocument:
        Version: '2012-10-17'
        Statement:
        - Sid: AllowSagemakerCreate
            Effect: Allow
            Action: sagemaker:CreateTrainingJob
            Resource: !Sub arn:${IAMPartition}:sagemaker:${AWS::Region}:${AWS::AccountId}:training-job/*
        - Sid: AllowSagemakerDescribe
            Effect: Allow
            Action: sagemaker:DescribeTrainingJob
            Resource: !Sub arn:${IAMPartition}:sagemaker:${AWS::Region}:${AWS::AccountId}:training-job/*
        - Sid: AllowSagemakerDeploy
            Effect: Allow
            Action:
                - "sagemaker:CreateModel"
                - "sagemaker:CreateEndpointConfig"
                - "sagemaker:CreateEndpoint"
                - "sagemaker:DescribeModel"
                - "sagemaker:DescribeEndpoint"
                - "sagemaker:InvokeEndpoint"
            Resource:
                - !Sub "arn:${IAMPartition}:sagemaker:${AWS::Region}:${AWS::AccountId}:endpoint/*"
                - !Sub "arn:${IAMPartition}:sagemaker:${AWS::Region}:${AWS::AccountId}:model/*"
                - !Sub "arn:${IAMPartition}:sagemaker:${AWS::Region}:${AWS::AccountId}:endpoint-config/*"
    ```
    """
    stack = Stack.of(scope)
    make_id: TNamerFn = make_namer_fn(id_prefix)
    allow_create_sagemaker_training_jobs = iam.PolicyStatement(
        actions=["sagemaker:CreateTrainingJob", "sagemaker:DescribeTrainingJob"],
        effect=iam.Effect.ALLOW,
        resources=[f"arn:aws:sagemaker:{stack.region}:{stack.account}:training-job/*"],
    )

    allow_deploy_to_sagemaker = iam.PolicyStatement(
        actions=[
            "sagemaker:CreateModel",
            "sagemaker:CreateEndpointConfig",
            "sagemaker:CreateEndpoint",
            "sagemaker:DescribeModel",
            "sagemaker:DescribeEndpoint",
            "sagemaker:InvokeEndpoint",
        ],
        effect=iam.Effect.ALLOW,
        resources=[
            f"arn:aws:sagemaker:{stack.region}:{stack.account}:endpoint/*",
            f"arn:aws:sagemaker:{stack.region}:{stack.account}:model/*",
            f"arn:aws:sagemaker:{stack.region}:{stack.account}:endpoint-config/*",
        ],
    )

    allow_sagemaker_policy = iam.Policy(
        scope=scope,
        id=make_id("allow-sagemaker"),
        document=iam.PolicyDocument(
            statements=[allow_create_sagemaker_training_jobs, allow_deploy_to_sagemaker]
        ),
    )

    return allow_sagemaker_policy


def make__allow_pass_role_to_sagemaker_service__policy(
    scope: Construct,
    id_prefix: str,
):
    """
    TODO: what is this for?

    ```yaml
    PolicyName: IAM_PASS_ROLE
    PolicyDocument:
        Version: '2012-10-17'
        Statement:
            Sid: AllowPassRole
            Effect: Allow
            Action: iam:PassRole
            Resource: '*'
            Condition:
                StringEquals:
                iam:PassedToService: sagemaker.amazonaws.com
    ```
    """
    make_id: TNamerFn = make_namer_fn(id_prefix)

    allow_pass_role_to_sagemaker_stmt = iam.PolicyStatement(
        actions=["iam:PassRole"],
        effect=iam.Effect.ALLOW,
        resources=["*"],
    )
    allow_pass_role_to_sagemaker_stmt.add_condition(
        "StringEquals", {"iam:PassedToService": "sagemaker.amazonaws.com"}
    )

    allow_pass_role_to_sagemaker_policy = iam.Policy(
        scope=scope,
        id=make_id("iam-pass-role"),
        document=iam.PolicyDocument(statements=[allow_pass_role_to_sagemaker_stmt]),
    )

    return allow_pass_role_to_sagemaker_policy


def make__allow_put_cloudwatch_logs__policy(
    scope: Construct, id_prefix: str
) -> iam.Policy:
    """
    Create a DynamoDB table used to store information/state of Metaflow Flow runs when using step functions.

    ```yaml
    PolicyName: Cloudwatch
        PolicyDocument:
            Version: '2012-10-17'
            Statement:
            - Sid: AllowPutLogs
                Effect: Allow
                Action:
                    - 'logs:CreateLogStream'
                    - 'logs:PutLogEvents'
                Resource: '*'
    ```
    """
    make_id: TNamerFn = make_namer_fn(id_prefix)

    allow_put_logs = iam.Policy(
        scope=scope,
        id=make_id("allow-put-logs"),
        document=iam.PolicyDocument(statements=[iam.PolicyStatement(
        actions=[
            "logs:CreateLogStream",
            "logs:PutLogEvents",
        ],
        effect=iam.Effect.ALLOW,
        resources=["*"],
    )]),
    )

    return allow_put_logs
