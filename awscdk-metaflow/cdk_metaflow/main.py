"""
This file is re-implementing the official CloudFormation template.
We have a saved copy called ./official-metaflow-template.yml you can reference.

After we're done reimplementing that file, we'll break this file up into
constructs, making the interfaces values like ARNs, IDs, hostnames, AWS secrets, etc.
rather than AWS CDK object references. That way you could easily use only the pieces
of this construct library that you want--even choosing to create some parts
manually and letting CDK manage only the other portions.

Want your ECS cluster to be a bunch of on-prem ECS Anywhere instances?
Or maybe a mix of on-prem and spot instances for failover if your on-prem instances are over scheduled?
Or to use Auth0 instead of Cognito for the UI?
Or just a VPN for the UI?
Or a non-RDS postgres database because RDS is expensive?
etc. etc. etc.

Things like the above ^^^ are made possible through the use of well designed constructs.

TODO: add HTTPS to this setup

Ongoing exploration and ideas:

1. Is it possible to use the default VPC? That would save a lot of money.
2. Can we point the UI at a database in lightsail?
3. By default, is the sagemaker notebook protected? Should we add an option to set up a VPN for it?
4. Could the interface for the postgres db simply be a secret in secrets manager? The goal here
   would be that you could host your sql database anywhere, maybe lightsail or on-prem. DBs can
   be one of the priciest parts of an architecture.
5. We could accept a HostedZone (for a registered domain) as input and add pretty domains
   for each of the components, e.g. 
   
   Subdomain                 Example Top-level Domain   Purpose
   ---------                 ------------------------   -------
   metaflow-db               .mlops-club.com            Metadata database
   metaflow-metadata-service .mlops-club.com            Metadata service
   metaflow                  .mlops-club.com            UI webserver
   metaflow-ui-backend       .mlops-club.com            UI backend

   To achieve this, it would be good to have the domain be registered in another
   account so we can freely delete/recreate the entire Metaflow AWS account
   without losing any irreplacable state. This would also allow us to use
   different accounts with their own subdomains for environments 
   (eric-dev, ryan-dev, staging, prod, etc.) if we ever get this to the point we 
   want to open source it to a larger group for testing.

   NOTE: each of the services should be able to have a nice domain, but they shouldn't *have* to
   have one.
6. The resources here add up. We have a NAT gateway, ALB, an RDS database, and
   3 Fargate containers. There is also S3 and Dynamo storage. I wonder if we could
   make this template in such a way that we can destroy the running resources when
   we're not actively using Metaflow, but keep all of the data. Then we could
   turn the resources back on whenever we're ready to run more experiments.
7. You could possibly run most of Metaflow on a single on-premise Linux box,
   and register more on-prem GPU machines with ECS Anywhere. I haven't validated this
   idea yet, but Ville Tuulos--co-creator of Metaflow--thought it sounded like a fun
   experiment: https://outerbounds-community.slack.com/archives/C02116BBNTU/p1666060632779379
"""

from typing import Optional
import aws_cdk as cdk
from aws_cdk import Stack, CfnOutput
from cdk_metaflow.config import MetaflowStackConfig
from constructs import Construct
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_rds as rds
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_batch_alpha as batch

from cdk_metaflow.config import MetaflowStackConfig, MetaflowUIBackendServiceConstants
from cdk_metaflow.metadata_service.ecs import MetadataService
from cdk_metaflow.ui.ecs import UIBackendService, UIFrontendService
from cdk_metaflow.computation.batch import make_fargate_compute_environment,make_batch_job_queue
from cdk_metaflow.computation.client_iam_roles import make_ecs_s3_access_iam_role
from cdk_metaflow.computation.dynamo_sfn_state_table import (
    make_step_function_state_ddb_table,
)


class MetaflowStack(Stack):
    def __init__(
        self, scope: Construct, construct_id: str, config: MetaflowStackConfig, **kwargs
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        Metaflow(
            self,
            "metaflow-deployment",
            vpc_cidr=config.vpc_cidr,
            enable_ui=True,
            enable_sagemaker=True,
        )


class Metaflow(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        vpc: Optional[ec2.Vpc] = None,
        vpc_cidr: Optional[str] = None,
        artifacts_bucket_name: Optional[str] = None,
        enable_ui: Optional[bool] = False,
        enable_sagemaker: Optional[bool] = False,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        assert not (
            vpc and vpc_cidr
        ), "vpc and vpc_cidr cannot both be set; set only one"

        vpc: ec2.Vpc = vpc or make_low_cost_vpc(scope=self, cidr=vpc_cidr)
        artifacts_bucket: s3.Bucket = lookup_or_create_artifacts_bucket(
            self, construct_id, artifacts_bucket_name=artifacts_bucket_name
        )
        metadata_database = MetadataDatabase(
            self, id="metaflow-metadata-db", vpc=vpc, database_name="metaflow"
        )

        # Begin batch and step functions

        sfn_state_ddb_table: dynamodb.Table = make_step_function_state_ddb_table(
            scope=self,
            id_prefix=construct_id,
        )
        ecs_s3_access_iam_role = make_ecs_s3_access_iam_role(
            allow_sagemaker=enable_sagemaker,
            artifacts_bucket_name=artifacts_bucket.bucket_name,
            scope=self,
            id_prefix=construct_id,
            flow_run_state_ddb_table_name=sfn_state_ddb_table.table_name,
        )
        self.make_output(
            "METAFLOW_ECS_S3_ACCESS_IAM_ROLE",
            ecs_s3_access_iam_role.role_arn,
            "set [METAFLOW_ECS_S3_ACCESS_IAM_ROLE] as this value when running 'metaflow configure aws'",
        )
        compute_environment: batch.ComputeEnvironment = make_fargate_compute_environment(
            scope=self, id_prefix=construct_id, vpc_with_metadata_service=vpc
        )
        batch_job_queue: batch.JobQueue = make_batch_job_queue(scope=self, id_prefix=construct_id, compute_environments=[compute_environment])

        self.make_output("METAFLOW_BATCH_JOB_QUEUE", batch_job_queue.job_queue_arn, "set [METAFLOW_BATCH_JOB_QUEUE] as this value when running 'metaflow configure aws'")

        # Begin - metadata service and UI

        alb = elbv2.ApplicationLoadBalancer(
            self,
            "application-load-balancer",
            vpc=vpc,
            internet_facing=True,
        )

        ecs_cluster_in_vpc = ecs.Cluster(self, "metaflow-cluster", vpc=vpc)

        metadata_svc = MetadataService(
            self,
            "metaflow-metadata-service",
            db_host=metadata_database.db_instance.db_instance_endpoint_address,
            db_port=metadata_database.db_instance.db_instance_endpoint_port,
            db_user=metadata_database.db_instance.secret.secret_value_from_json(
                "username"
            ).to_string(),
            db_password_token=metadata_database.db_instance.secret.secret_value_from_json(
                "password"
            ).to_string(),
            db_name="metaflow",
            db_security_group=metadata_database.db_security_group,
            ecs_cluster_in_vpc=ecs_cluster_in_vpc,
            alb=alb,
        )

        if enable_ui:
            ui_backend_svc = UIBackendService(
                self,
                "metaflow-ui-backend-service",
                load_balancer_listener_port=MetaflowUIBackendServiceConstants.CONTAINER_PORT,
                db_host=metadata_database.db_instance.db_instance_endpoint_address,
                db_port=metadata_database.db_instance.db_instance_endpoint_port,
                db_user=metadata_database.db_instance.secret.secret_value_from_json(
                    "username"
                ).to_string(),
                db_password_token=metadata_database.db_instance.secret.secret_value_from_json(
                    "password"
                ).to_string(),
                db_name=metadata_database.database_name,
                metaflow_artifacts_bucket_name=artifacts_bucket.bucket_name,
                db_security_group=metadata_database.db_security_group,
                ecs_cluster_in_vpc=ecs_cluster_in_vpc,
                alb=alb,
            )

            ui_frontend_svc = UIFrontendService(
                self,
                "metaflow-ui-frontend-service",
                db_security_group=metadata_database.db_security_group,
                ecs_cluster_in_vpc=ecs_cluster_in_vpc,
                backend_url=ui_backend_svc.url,
                alb=alb,
            )

            # expose outputs in the CloudFormation console
            # self.make_output("UIFrontendURL", ui_frontend_svc.url)
            self.make_output("UIBackendURL", ui_backend_svc.url)

        # self.make_output("MetadataServiceURL", metadata_svc.url)
        # self.make_output("MetadataAPIDocsUrl", metadata_svc.docs_url)
        db_url = metadata_database.db_instance.db_instance_endpoint_address
        self.make_output("DatabaseUrl", db_url)
        self.make_output("LoadBalancerUrl", alb.load_balancer_dns_name)
        self.make_output("MetadataAndUIEcsCluster", ecs_cluster_in_vpc.cluster_arn)

    def make_output(
        self,
        name: str,
        value: str,
        description: Optional[str] = None,
    ) -> CfnOutput:
        return CfnOutput(scope=self, id=name, description=description, value=value)


class MetadataDatabase(Construct):
    def __init__(
        self,
        scope: "Construct",
        id: str,
        vpc: ec2.Vpc,
        database_name: Optional[str] = "metaflow",
        **kwargs,
    ):
        super().__init__(scope, id, **kwargs)
        self.database_name = database_name

        self.db_security_group = ec2.SecurityGroup(
            self, "db-security-group", allow_all_outbound=True, vpc=vpc
        )

        # TODO: have a "dev mode" that conditionally enables this parameter. In general, the DB
        # should not be accessible to the public.
        self.db_security_group.add_ingress_rule(
            peer=ec2.Peer.ipv4("0.0.0.0/0"), connection=ec2.Port.tcp(5432)
        )

        self.db_instance = rds.DatabaseInstance(
            self,
            "metadata-db",
            removal_policy=cdk.RemovalPolicy.DESTROY,
            engine=rds.DatabaseInstanceEngine.postgres(
                version=rds.PostgresEngineVersion.VER_14
            ),
            instance_type=ec2.InstanceType("t3.micro"),  # ~$7/mo
            database_name=database_name,
            storage_type=rds.StorageType.GP2,
            # secret in AWS SecretsManager of the form {"username": "master", "password": "xxxx", "port": xxxx}
            credentials=rds.Credentials.from_username(username="master"),
            multi_az=False,
            security_groups=[self.db_security_group],
            vpc=vpc,
            # TODO: consider NOT putting the database in a public subnet 🤣
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
        )


def make_low_cost_vpc(scope: Construct, cidr: str) -> ec2.Vpc:
    return ec2.Vpc(
        scope=scope,
        id="vpc",
        enable_dns_support=True,
        enable_dns_hostnames=True,
        cidr=cidr,
        max_azs=2,
        nat_gateways=1,
        nat_gateway_provider=ec2.NatProvider.instance(
            instance_type=ec2.InstanceType("t2.nano")
        ),
        subnet_configuration=[
            ec2.SubnetConfiguration(
                map_public_ip_on_launch=True,
                name="public",
                subnet_type=ec2.SubnetType.PUBLIC,
                cidr_mask=24,
            ),
            ec2.SubnetConfiguration(
                name="private",
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                cidr_mask=24,
            ),
        ],
    )


def lookup_or_create_artifacts_bucket(
    scope: Construct, id_prefix: str, artifacts_bucket_name: Optional[str] = None
) -> s3.Bucket:
    construct_id = f"{id_prefix}-artifacts-bucket"
    artifacts_bucket: Optional[
        s3.Bucket
    ] = artifacts_bucket_name and s3.Bucket.from_bucket_name(
        scope, construct_id, bucket_name=artifacts_bucket_name
    )
    artifacts_bucket: s3.Bucket = artifacts_bucket or s3.Bucket(
        scope,
        construct_id,
        auto_delete_objects=True,
        # TODO: you miiiiight want to keep your bucket around on deletion to save
        # all your precious model weights and other artifacts. This is set to destroy for convenience
        # during development. Retain would probably be better.
        removal_policy=cdk.RemovalPolicy.DESTROY,
    )
    return artifacts_bucket
