from typing import Optional
import aws_cdk as cdk
from aws_cdk import Stack, CfnOutput
from cdk_metaflow.config import MetaflowStackConfig
from constructs import Construct
from aws_cdk import aws_ecs_patterns as ecs_patterns
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_rds as rds
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_elasticloadbalancingv2 as elbv2

from cdk_metaflow.webservice import Webservice, PortMapping
from cdk_metaflow.utils import make_namer_fn

from cdk_metaflow.config import (
    MetaflowUIBackendServiceConstants,
    MetaflowUIFrontendServiceConstants,
)

class UIBackendService(Construct):

    def __init__(
        self,
        scope: "Construct",
        construct_id: str,
        db_host: str,
        db_port: str,
        db_user: str,
        db_password_token: str,
        db_name: str,
        db_security_group: ec2.SecurityGroup,
        metaflow_artifacts_bucket_name: str,
        ecs_cluster_in_vpc: ecs.Cluster,
        alb: elbv2.ApplicationLoadBalancer,
        load_balancer_listener_port: int,
        container_port: Optional[int] = MetaflowUIBackendServiceConstants.CONTAINER_PORT,
        url_path_prefix: Optional[str] = MetaflowUIBackendServiceConstants.URL_PATH_PREFIX,
        max_container_cpu_mb: Optional[int] = MetaflowUIBackendServiceConstants.CONTAINER_CPU,
        max_container_memory_mb: Optional[int] = MetaflowUIBackendServiceConstants.CONTAINER_MEMORY,
        desired_container_count: Optional[int] = MetaflowUIBackendServiceConstants.DESIRED_COUNT,
        health_check_path: Optional[str] = MetaflowUIBackendServiceConstants.HEALTHCHECK_PATH,
        min_tasks: Optional[int] = 1,
        max_tasks: Optional[int] = 1,
    ) -> None:
        super().__init__(scope, construct_id)
        self.namer = make_namer_fn(construct_id)

        Webservice(
            self,
            construct_id=self.namer("Webservice"),
            load_balancer_to_container_port_mappings=[
                PortMapping(
                    listener_port=load_balancer_listener_port, 
                    container_port=container_port, 
                    path_pattern=f"{url_path_prefix}*"
                ),
            ],
            docker_image=ecs.ContainerImage.from_registry(
                MetaflowUIBackendServiceConstants.IMAGE_URL
            ),
            docker_container_command=[
                "/opt/latest/bin/python3",
                "-m",
                "services.ui_backend_service.ui_server",
            ],
            health_check_path=health_check_path,
            container_env_vars_overrides={
                "MF_METADATA_DB_HOST": db_host,
                "MF_METADATA_DB_PORT": db_port,
                "MF_METADATA_DB_USER": db_user,
                "MF_METADATA_DB_PSWD": db_password_token,
                "MF_METADATA_DB_NAME": db_name,
                "UI_ENABLED": "1",
                "PATH_PREFIX": url_path_prefix,
                # NOTE: We could use minIO here if we really wanted to save money and run
                # this all on-prem.
                "MF_DATASTORE_ROOT": f"s3://{metaflow_artifacts_bucket_name}/metaflow",
                "METAFLOW_DATASTORE_SYSROOT_S3": f"s3://{metaflow_artifacts_bucket_name}/metaflow",
                "LOGLEVEL": "DEBUG",
                # NOTE: the metaflow UI webserver is its own backend server; accessed e.g. localhost:8082/api/metadata
                "METAFLOW_SERVICE_URL": f"http://localhost:{container_port}{url_path_prefix}metadata",
                # NOTE: I wonder if there is a "local" mode or something else we could use
                # to run a fully working version of metaflow using docker-compose or docker swarm.
                # Local dev environments are underrated!
                "METAFLOW_DEFAULT_DATASTORE": "s3",
                "METAFLOW_DEFAULT_METADATA": "service",
            },
            ecs_cluster_in_vpc=ecs_cluster_in_vpc,
            ecs_memory_limit_mb=max_container_memory_mb,
            ecs_cpu_size=max_container_cpu_mb,
            ecs_desired_num_instances=desired_container_count,
            load_balancer=alb,
            min_tasks=min_tasks,
            max_tasks=max_tasks,
            service_security_groups=[db_security_group],
        )

        self.url = f"http://{alb.load_balancer_dns_name}:{load_balancer_listener_port}{url_path_prefix}"


class UIFrontendService(Construct):
    """
    NOTE: Should we put 'ECS' in the name of these classes since they are so coupled to running in ECS?
    I might want to run these services on a lightsail instance. If I did that, I could avoid these
    classes altogether and write my own construct that puts them there.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        ecs_cluster_in_vpc: ecs.Cluster,
        alb: elbv2.ApplicationLoadBalancer,
        backend_url: str,
        container_port: Optional[int] = MetaflowUIFrontendServiceConstants.CONTAINER_PORT,
        max_container_cpu_mb: Optional[int] = MetaflowUIFrontendServiceConstants.CONTAINER_CPU,
        max_container_memory_mb: Optional[int] = MetaflowUIFrontendServiceConstants.CONTAINER_MEMORY,
        desired_container_count: Optional[int] = MetaflowUIFrontendServiceConstants.DESIRED_COUNT,
        min_tasks: Optional[int] = 1,
        max_tasks: Optional[int] = 1,
        # tls_cert: acm.Certificate,
        **kwargs,
    ):
        """Create an ECS Service that runs the containerized frontend server."""
        super().__init__(scope, construct_id, **kwargs)
        self.namer = make_namer_fn(construct_id)

        Webservice(
            self,
            construct_id=self.namer("UIService"),
            load_balancer_to_container_port_mappings=[
                PortMapping(
                    listener_port=container_port, 
                    container_port=container_port, 
                    path_pattern="*"
                ),
            ],
            docker_image=ecs.ContainerImage.from_registry(
                MetaflowUIFrontendServiceConstants.IMAGE_URL
            ),
            health_check_path="/",
            container_env_vars_overrides={
                "METAFLOW_SERVICE": backend_url
            },
            ecs_cluster_in_vpc=ecs_cluster_in_vpc,
            ecs_memory_limit_mb=max_container_memory_mb,
            ecs_cpu_size=max_container_cpu_mb,
            ecs_desired_num_instances=desired_container_count,
            load_balancer=alb,
            min_tasks=min_tasks,
            max_tasks=max_tasks,
        )

        self.url = f"http://{alb.load_balancer_dns_name}"