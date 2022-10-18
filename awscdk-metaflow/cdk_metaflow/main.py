"""
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
from aws_cdk import aws_ecs_patterns as ecs_patterns
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_rds as rds
from aws_cdk import aws_elasticloadbalancingv2 as elbv2

from cdk_metaflow.config import MetaflowMetadataServiceConstants

from aws_cdk import aws_ec2 as ec2

#   RDSMasterInstance:
#     Type: AWS::RDS::DBInstance
#     Properties:
#       DBName: 'metaflow'
#       AllocatedStorage: 20
#       DBInstanceClass: 'db.t2.small'
#       DeleteAutomatedBackups: 'true'
#       StorageType: 'gp2'
#       Engine: 'postgres'
#       EngineVersion: '11'
#       MasterUsername: !Join ['', ['{{resolve:secretsmanager:', !Ref MyRDSSecret, ':SecretString:username}}' ]]
#       MasterUserPassword: !Join ['', ['{{resolve:secretsmanager:', !Ref MyRDSSecret, ':SecretString:password}}' ]]
#       VPCSecurityGroups:
#         - !Ref 'RDSSecurityGroup'
#       DBSubnetGroupName: !Ref 'DBSubnetGroup'
#   MyRDSSecret:
#     Type: "AWS::SecretsManager::Secret"
#     Properties:
#       Description: "This is a Secrets Manager secret for an RDS DB instance"
#       GenerateSecretString:
#         SecretStringTemplate: '{"username": "master"}'
#         GenerateStringKey: "password"
#         PasswordLength: 16
#         ExcludeCharacters: '"@/\'
#   SecretRDSInstanceAttachment:
#     Type: "AWS::SecretsManager::SecretTargetAttachment"
#     Properties:
#       SecretId: !Ref MyRDSSecret
#       TargetId: !Ref RDSMasterInstance
#       TargetType: AWS::RDS::DBInstance


class MetaflowStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, config: MetaflowStackConfig, **kwargs) -> None:

        super().__init__(scope, construct_id, **kwargs)

        # vpc = ec2.Vpc.from_lookup(self, "default-vpc", vpc_name="Default VPC")

        vpc = ec2.Vpc(
            self,
            "vpc",
            enable_dns_support=True,
            enable_dns_hostnames=True,
            cidr=config.vpc_cidr,
            max_azs=2,
            nat_gateways=1,
            nat_gateway_provider=ec2.NatProvider.instance(instance_type=ec2.InstanceType("t2.nano")),
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

        # db_secret = rds.DatabaseSecret(self, "metaflow-db-secret", username="master")
        # db_secret = rds.Credentials.from_username(username="master")
        db_security_group = ec2.SecurityGroup(self, "db-security-group", allow_all_outbound=True, vpc=vpc)

        # TODO: have a "dev mode" that conditionally enables this parameter. In general, the DB
        # should not be accessible to the public.
        db_security_group.add_ingress_rule(peer=ec2.Peer.ipv4("0.0.0.0/0"), connection=ec2.Port.tcp(5432))

        postgres_db = rds.DatabaseInstance(
            self,
            "metadata-db",
            removal_policy=cdk.RemovalPolicy.DESTROY,
            engine=rds.DatabaseInstanceEngine.postgres(version=rds.PostgresEngineVersion.VER_14),
            instance_type=ec2.InstanceType("t3.micro"),  # ~$7/mo
            database_name="metaflow",
            storage_type=rds.StorageType.GP2,
            # secret in AWS SecretsManager of the form {"username": "master", "password": "xxxx", "port": xxxx}
            credentials=rds.Credentials.from_username(username="master"),
            multi_az=False,
            security_groups=[db_security_group],
            vpc=vpc,
            # TODO: consider NOT putting the database in a public subnet 🤣
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
        )

        alb = elbv2.ApplicationLoadBalancer(
            self,
            "application-load-balancer",
            vpc=vpc,
            internet_facing=True,
        )
        ecs_cluster_in_vpc = ecs.Cluster(self, "metaflow-cluster", vpc=vpc)

        # scalable_task_count = svc.service.auto_scale_task_count(min_capacity=1, max_capacity=1)

        self.make_output("DatabaseUrl", postgres_db.db_instance_endpoint_address)
        self.make_output("LoadBalancerUrl", alb.load_balancer_dns_name)

        self.make_metaflow_metadata_service(
            db_host=postgres_db.db_instance_endpoint_address,
            db_port=postgres_db.db_instance_endpoint_port,
            db_user=postgres_db.secret.secret_value_from_json("username").to_string(),
            db_password_token=postgres_db.secret.secret_value_from_json("password").to_string(),
            db_security_group=db_security_group,
            ecs_cluster_in_vpc=ecs_cluster_in_vpc,
            alb=alb,
        )

    def make_output(
        self,
        name: str,
        value: str,
        description: Optional[str] = None,
    ) -> CfnOutput:
        return CfnOutput(scope=self, id=name, description=description, value=value)

    def make_metaflow_metadata_service(
        self,
        db_host: str,
        db_port: str,
        db_user: str,
        db_password_token: str,
        db_security_group: ec2.SecurityGroup,
        ecs_cluster_in_vpc: ecs.Cluster,
        alb: elbv2.ApplicationLoadBalancer,
    ) -> ecs_patterns.ApplicationLoadBalancedFargateService:

        svc = ecs_patterns.ApplicationLoadBalancedFargateService(
            self,
            "metaflow-metadata-service-v2",
            cluster=ecs_cluster_in_vpc,
            task_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            security_groups=[db_security_group],
            assign_public_ip=True,
            load_balancer=alb,
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
            listener_port=80,
            desired_count=MetaflowMetadataServiceConstants.DESIRED_COUNT,
            cpu=MetaflowMetadataServiceConstants.CONTAINER_CPU,
            memory_limit_mib=MetaflowMetadataServiceConstants.CONTAINER_CPU,
            task_image_options=ecs_patterns.ApplicationLoadBalancedTaskImageOptions(
                image=ecs.ContainerImage.from_registry("netflixoss/metaflow_metadata_service:v2.2.3"),
                container_port=MetaflowMetadataServiceConstants.CONTAINER_PORT,
                environment={
                    "MF_METADATA_DB_HOST": db_host,
                    "MF_METADATA_DB_PORT": db_port,
                    "MF_METADATA_DB_USER": db_user,
                    "MF_METADATA_DB_PSWD": db_password_token,
                    "MF_METADATA_DB_NAME": "metaflow",
                },
                log_driver=ecs.LogDriver.aws_logs(stream_prefix="metadata-service"),
            ),
        )

        # healthcheck ECS will use to determine whether to terminate/restart the container
        svc.target_group.configure_health_check(
            port=str(MetaflowMetadataServiceConstants.CONTAINER_PORT),
            path=MetaflowMetadataServiceConstants.HEALTHCHECK_PATH,
        )

        self.make_output("MetadataServiceDocsUrl", f"{alb.load_balancer_dns_name}/api/doc")

        return svc
