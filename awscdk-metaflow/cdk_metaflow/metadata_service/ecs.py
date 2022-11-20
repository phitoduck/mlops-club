from typing import Optional
import aws_cdk as cdk
from aws_cdk import Stack, CfnOutput
from cdk_metaflow.config import MetaflowStackConfig
from constructs import Construct
from aws_cdk import aws_ecs_patterns as ecs_patterns
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_rds as rds
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_elasticloadbalancingv2 as elbv2

from cdk_metaflow.config import (
    MetaflowMetadataServiceConstants,
    MetaflowUIBackendServiceConstants,
    MetaflowUIFrontendServiceConstants,
)

from aws_cdk import aws_ec2 as ec2

class MetadataService(Construct):
    """
    The Metaflow Metadata Service.
    
    Unnecessary if you use "Local" mode
    -----------------------------------
    
    This service is used by the Metaflow client SDK to track artifacts, flow (DAG) runs, etc.
    Without this service, you can run Metaflow in "local" mode. In local mode, these artifacts
    are stored on local disk in a folder. 

    Necessary when you want to collaborate
    --------------------------------------
    
    Local mode works well if you don't need to collaborate
    with other developers/scientists. Once you need to collaborate, you can run this set of resources:

    Resources
    ---------

    - the metadata service (running in a container)
    - an S3 bucket for the larger artifacts
    - a Postgres database that documents which runs have happened, where the artifacts are for each run, etc.

    Client
    ------

    The metaflow client needs to be able to reach this service. Two things may need to be configured
    to reach the metadata service:

    1. Your laptop (or a cloud development machine)
    2. (Optional) Workers in AWS Batch (or Kubernetes); note that you don't have to enable cloud workers 
      for running flows. You could choose to have all devs run the flows locally and just use the tracking 
      server to save the metadata and artifacts.
    """

    def __init__(
        self,
        scope: "Construct",
        id: str,
        db_host: str,
        db_port: str,
        db_user: str,
        db_password_token: str,
        db_name: str,
        db_security_group: ec2.SecurityGroup,
        ecs_cluster_in_vpc: ecs.Cluster,
        alb: elbv2.ApplicationLoadBalancer,
        container_port: Optional[int] = MetaflowMetadataServiceConstants.CONTAINER_PORT,
        max_container_cpu_mb: Optional[int] = MetaflowMetadataServiceConstants.CONTAINER_CPU,
        max_container_memory_mb: Optional[int] = MetaflowMetadataServiceConstants.CONTAINER_MEMORY,
        desired_container_count: Optional[int] = MetaflowMetadataServiceConstants.DESIRED_COUNT,
        **kwargs,
    ) -> None:
        """Initialize a MetadataService construct.

        :param scope: parent construct/stack
        :param id: construct id
        :param db_host: host of the relational database
        :param db_port: port of the relational database
        :param db_user: user in the relational database
        :param db_password_token: either a plaintext password (bad idea); or reference that resolves
        :param db_name: name of the database within the database instance where the metadata is stored
        :param db_security_group: security group that provides access to the database on the needed port
        :param ecs_cluster_in_vpc: the cluster where this service will be deployed to; it should be configured with a VPC
        :param alb: load balancer that this construct will add a listener to; can be shared with other services, but not guaranteed not to conflict with existing listeners on the ALB
        :param container_port: the port that the metadata service listens on; it is also the port that the load balancer listens on. TODO: we should decouple these, I don't think we have control of which port the container actually listens on.
        :param max_container_cpu_mb: max vcpu's of the container task. See ECS fargate VCPU docs for valid values.
        :param max_container_memory_mb: max RAM of the container task. See ECS fargate memory docs for valid values.
        :param desired_container_count: how many instances to default to after high traffic spikes settle down. TODO: should we expose the min count and max count?
        """
        super().__init__(scope, id, **kwargs)

        svc = ecs_patterns.ApplicationLoadBalancedFargateService(
            self,
            "metaflow-metadata-service-v2",
            cluster=ecs_cluster_in_vpc,
            task_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            security_groups=[db_security_group],
            assign_public_ip=True,
            load_balancer=alb,
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
            listener_port=80,
            # certificate=tls_cert,
            # protocol=elbv2.ApplicationProtocol.HTTPS,
            desired_count=desired_container_count,
            cpu=max_container_cpu_mb,
            memory_limit_mib=max_container_memory_mb,
            task_image_options=ecs_patterns.ApplicationLoadBalancedTaskImageOptions(
                image=ecs.ContainerImage.from_registry(
                    MetaflowMetadataServiceConstants.IMAGE_URL
                ),
                container_port=container_port,
                environment={
                    "MF_METADATA_DB_HOST": db_host,
                    "MF_METADATA_DB_PORT": db_port,
                    "MF_METADATA_DB_USER": db_user,
                    "MF_METADATA_DB_PSWD": db_password_token,
                    "MF_METADATA_DB_NAME": db_name,
                },
                log_driver=ecs.LogDriver.aws_logs(stream_prefix="metadata-service"),
            ),
        )

        # healthcheck ECS will use to determine whether to terminate/restart the container
        svc.target_group.configure_health_check(
            port=str(container_port),
            path=MetaflowMetadataServiceConstants.HEALTHCHECK_PATH,
        )

        self.url = f"{alb.load_balancer_dns_name}"
        self.docs_url = f"{self.url}/api/doc"