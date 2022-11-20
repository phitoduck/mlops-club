"""
Define a stack with all necessary resources for a functional, private, fargate cluster.

This stack creates the fargate service and all the 'stuff' necessary for it to run. It
uses the dockerfile defined at the root of the project, moves the image to an ECR, points
the fargate cluster to the ECR, creates a load balancer, and creates routes, route tables,
permissions, and other associations.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Dict, Optional, Union, List
from collections import Counter

import aws_cdk as cdk
import aws_cdk.aws_secretsmanager as secretsmanager
from aws_cdk import Stack, SymlinkFollowMode
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_ecs_patterns as ecs_patterns
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from aws_cdk.aws_ecs import PropagatedTagSource
from aws_cdk.aws_logs import RetentionDays
from constructs import Construct
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk import aws_ecr_assets as ecr_assets

from dataclasses import dataclass, field

LOG_RETENTION: RetentionDays = RetentionDays.THREE_DAYS


@dataclass
class PortMapping:
    """Class used to represent port mappings from the load balancer to the container."""

    listener_port: int
    container_port: int
    path_pattern: Optional[str] = field(default="*")

    @staticmethod
    def do_port_mappings_conflict(port_mappings: List["PortMapping"]) -> bool:
        """
        Return true if any of the port mappings conflict.
        
        The each listener port should appear only once.
        """
        listener_ports = [port_mapping.listener_port for port_mapping in port_mappings]
        listener_port_counts = Counter(listener_ports)
        for _, num_listener_port_occurences in listener_port_counts.items():
            if num_listener_port_occurences > 1:
                return True
        return False

    @staticmethod
    def map_listener_port_to_mapping(port_mappings: List[PortMapping]) -> Dict[int, PortMapping]:
        return {
            port_mapping.listener_port: port_mapping for port_mapping in port_mappings
        }

    @staticmethod
    def list_listener_ports(port_mappings: List[PortMapping]) -> List[int]:
        return [port_mapping.listener_port for port_mapping in port_mappings]

    @staticmethod
    def list_container_ports(port_mappings: List[PortMapping]) -> List[int]:
        return [port_mapping.container_port for port_mapping in port_mappings]


class Webservice(Construct):
    """
    Resources for running a containerized, potentially UI-capable webservice in ECS Fargate.

    .. note::

        The containerized web-service does not necessarily need to expose a UI
        such as in the case of a REST API that returns no HTML.

        This construct supports UI-less services as well.

    In general, containerized web APIs (web services) can have any number of endpoints, each of which
    is *almost always* exactly one of these two types:

    1. "UI" endpoints -- serve HTML. Example: ``/docs`` in FastAPI apps)
    2. "non-UI" endpoints -- do not serve HTML. Example: ``/healthcheck``



    Protecting webservice endpoints

    TL;DR a recommended solution to protect a webservice's endpoints is to:

    a. protect the UI-endpoints using login-redirects with an AWS service such as AWS Application Load Balancer (ALB)
    b. protect the non-UI-endpoints using pure JWT upstream of the ALB with something like API Gateway

    .. note:: protection of UI and non-UI endpoints is not currently implemented in this construct.


    (1) Human-to-machine authentication

    UI endpoints may need to be protected by redirecting to a login UI if the client (usually a browser)
    does not have an auth token. In OAuth2 terms, the redirect-login-redirect-back process is called the
    "authorization code OAuth2 flow".

    **AWS Application Load Balancers are capable of detecting unauthenticated requests and
    initiating the authorization code flow**, redirecting non-logged in users to a login page
    which then redirects them back to their original URL when they finish.


    (2) Server-to-server (or machine-to-machine) authentication

    Non-UI endpoints have no need to support login-redirects. The need to redirect unauthenticated
    requests comes from the fact that humans interact with UI-endpoints via a browser.

    Browsers only execute GET requests with no additional parameters when typing a URL into the
    search bar.

    In contrast, client code is capable of (a) sending auth credentials inside of
    (b) requests of any type, POST, PATCH, GET, etc.

    **AWS Application Load Balancers are *not* capable of checking auth tokens in a server-to-server fashion**.

    Protecting non-UI endpoints with JWT needs to be done (a) in the application code itself, or
    (b) upstream of the ALB, e.g. in an API Gateway.

    :param scope: CDK parent construct
    :param construct_id: ID of this construct
    :param load_balancer_to_container_port_mappings: port mappings from the load balancer into the running task containers.
        For example,

        .. code-block:: python
            
            {
                80: 3333,
                8080: 5432,
            }

        would map ``<load balancer url>:80 -> container:3333`` and ``<load balancer url>:8080 -> container:5432``.
    :param docker_build_context: build context used when building the Docker image from the local Dockerfile
    :param health_check_path: an endpoint used for determining whether the service is healthy or should be restarted, e.g. ``/healthcheck``
    :param health_check_port: the port that will be used for health checks; defaults to the value if 
        ``load_balancer_to_container_port_mappings`` only has one key-value pair
    :param ecs_cpu_size: amount of vCPU's allocated to the task. We pay for this.
        Valid values for this parameter depend on the value used for ``ecs_memory_limit_mb``.
        See this reference for a list of valid values:
        https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task-cpu-memory-error.html
    :param ecs_memory_limit_mb: RAM allocated to the task. We pay for this.
        Valid values for this parameter depend on the value used for ``ecs_cpu_size``.
        See this reference for a list of valid values:
        https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task-cpu-memory-error.html
    :param ecs_desired_num_instances: number of instances to scale down to when load is calm
    :param min_tasks: minimum allowed instances that can be autoscaled to
    :param max_tasks: maximum allowed number of instances that can be autoscaled to
    :param reachable_outside_vpc: whether the service should be exposed to the public internet, or only accessible within the VPC (possibly by a VPN)
    :param scale_in_cooldown_seconds:
    :param scale_out_cooldown_seconds:
    :param target_memory_utilization_percent:
    :param target_cpu_utilization_percent:
    :param relative_dockerfile_path: path to the Dockerfile if not simply ``docker_build_context / Dockerfile``
    :param vpc_id: ID of an existing VPC, if not provided, a VPC will be created
    :param docker_build_args: mapping of environment variables passed as build arguments to ``docker build`` when building the docker image
    :param container_env_vars_overrides: environment variables which can override defaults or add new variables used during the container runtime
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        load_balancer_to_container_port_mappings: List[PortMapping],
        health_check_path: str,
        ecs_memory_limit_mb: int = 512,
        ecs_cpu_size: int = 256,
        ecs_desired_num_instances: int = 1,
        min_tasks: int = 1,
        max_tasks: int = 1,
        health_check_port: Optional[int] = None,
        reachable_outside_vpc: bool = False,
        scale_in_cooldown_seconds: Optional[int] = None,
        scale_out_cooldown_seconds: Optional[int] = None,
        target_memory_utilization_percent: int = 50,
        target_cpu_utilization_percent: int = 50,
        docker_container_command: Optional[List[str]] = None,
        relative_dockerfile_path: Optional[Union[str, Path]] = None,
        vpc_id: Optional[str] = None,
        docker_build_context: Optional[Union[str, Path]] = None,
        docker_build_args: Optional[Dict[str, str]] = None,
        container_env_vars_overrides: Optional[Dict[str, str]] = None,
        docker_image: Optional[ecs.ContainerImage] = None,
        service_security_groups: Optional[List[ec2.SecurityGroup]] = None,
        load_balancer: Optional[elbv2.ApplicationLoadBalancer] = None,
        ecs_cluster_in_vpc: Optional[ecs.Cluster] = None,
        **kwargs,
    ):
        super().__init__(scope, construct_id, **kwargs)
        self.namer = lambda name: f"{construct_id}-{name}"
        self.stack = Stack.of(self)

        assert not (
            docker_image and docker_build_context
        ), "docker_image and docker_build_context cannot both be set"
        assert not (docker_image and docker_build_args), "docker_image and docker_build_args cannot both be set"
        assert not (docker_image and relative_dockerfile_path), "docker_image and dockerfile_path cannot both be set"
        assert not (vpc_id and ecs_cluster_in_vpc), (
            "vpc_id and ecs_cluster_in_vpc cannot both be set; the vpc associated with the cluster will be used when ecs_cluster_in_vpc is set"
        )
        if not health_check_port:
            ports = load_balancer_to_container_port_mappings
            assert len(ports) == 1, (
                "health_check_port is unset; a default value could not be inferred"
                " because load_balancer_to_container_port_mappings has more than one mapping."
            )
            health_check_port: int = ports[0].container_port
        assert not PortMapping.do_port_mappings_conflict(load_balancer_to_container_port_mappings), (
            "Conflicting port mappings appear in load_balancer_to_container_port_mappings; is the same listener port listed more than once?"
        )

        log_group = logs.LogGroup(self, id="LogGroup")
        vpc: ec2.Vpc = ecs_cluster_in_vpc.vpc if ecs_cluster_in_vpc else create_or_lookup_vpc(scope=self, id_prefix=construct_id, vpc_id=vpc_id)
        self.load_balancer = load_balancer or elbv2.ApplicationLoadBalancer(
            self,
            f"{construct_id}ALB",
            vpc=vpc,
            internet_facing=reachable_outside_vpc,
        )

        self.ecs_cluster = ecs_cluster_in_vpc or ecs.Cluster(self, self.namer("Cluster"), vpc=vpc)

        task_definition: ecs.FargateTaskDefinition = make_webservice_task_definition(
            scope=self,
            id_prefix=construct_id,
            ecs_cpu_size=ecs_cpu_size,
            ecs_memory_limit_mb=ecs_memory_limit_mb,
            log_group=log_group,
            container_ports=PortMapping.list_container_ports(load_balancer_to_container_port_mappings),
            container_env_vars_overrides=container_env_vars_overrides or {},
            docker_image=docker_image,
            docker_build_context=docker_build_context,
            dockerfile_path=relative_dockerfile_path or Path("Dockerfile"),
            docker_build_args=docker_build_args or {},
            docker_container_command=docker_container_command,
        )

        container_port_to_target_group: Dict[
            int, elbv2.ApplicationTargetGroup
        ] = make_container_port_to_target_group_mapping(
            scope=scope,
            id_prefix=construct_id,
            vpc=vpc,
            health_check_port=health_check_port,
            health_check_path=health_check_path,
            container_ports=PortMapping.list_container_ports(load_balancer_to_container_port_mappings),
        )

        service: ecs.FargateService = make_service(
            scope=self,
            id_prefix=construct_id,
            desired_task_count=ecs_desired_num_instances,
            task_definition=task_definition,
            ecs_cluster_in_vpc=self.ecs_cluster,
            target_groups=list(container_port_to_target_group.values()),
            service_security_groups=service_security_groups,
        )

        configure_ecs_service_auto_scaling(
            id_prefix=construct_id,
            service=service,
            min_tasks=min_tasks,
            max_tasks=max_tasks,
            target_cpu_utilization_percent=target_cpu_utilization_percent,
            target_memory_utilization_percent=target_memory_utilization_percent,
            scale_in_cooldown_seconds=scale_in_cooldown_seconds,
            scale_out_cooldown_seconds=scale_out_cooldown_seconds,
        )

        lb_port_to_listener: Dict[int, elbv2.ApplicationListener] = make_load_balancer_listeners(
            scope=self,
            id_prefix=construct_id,
            load_balancer=self.load_balancer,
            container_port_to_target_group=container_port_to_target_group,
            load_balancer_to_container_port_mappings=load_balancer_to_container_port_mappings,
        )

        self.make_output("LoadBalancerUrl", self.load_balancer.load_balancer_dns_name)

    def make_output(
        self,
        id: str,
        value: str,
        description: Optional[str] = None,
    ):
        return cdk.CfnOutput(
            self,
            id=id,
            description=description,
            value=value,
        )

def make_webservice_task_definition(
    scope,
    id_prefix: str,
    ecs_cpu_size: int,
    ecs_memory_limit_mb: int,
    log_group: logs.LogGroup,
    container_ports: List[int],
    container_env_vars_overrides: Dict[str, str],
    docker_image: Optional[ecs.ContainerImage] = None,
    docker_build_context: Optional[Union[str, Path]] = None,
    dockerfile_path: Optional[Union[str, Path]] = None,
    docker_build_args: Optional[Dict[str, str]] = None,
    docker_container_command: Optional[List[str]] = None,
) -> ecs.FargateTaskDefinition:
    docker_image = docker_image or ecs.ContainerImage.from_asset(
        directory=docker_build_context and str(docker_build_context),
        file=str(dockerfile_path),
        build_args=docker_build_args,
        follow_symlinks=SymlinkFollowMode.ALWAYS,
        platform=ecr_assets.Platform.LINUX_AMD64,
    )

    # log stream name: stream-prefix/container-name/ecs-task-id
    log_driver = ecs.LogDriver.aws_logs(
        stream_prefix=id_prefix,
        log_group=log_group,
    )

    task_definition: ecs.FargateTaskDefinition = make_task_definition(
        scope=scope,
        id_prefix=id_prefix,
        ecs_cpu_size=ecs_cpu_size,
        ecs_memory_limit_mb=ecs_memory_limit_mb,
        docker_image=docker_image,
        container_ports=container_ports,
        container_env_vars_overrides=container_env_vars_overrides,
        container_command=docker_container_command,
    )

    _configure_ecs_task_execution_role(
        scope=scope,
        id_prefix=id_prefix,
        execution_role=task_definition.execution_role,
    )


    return task_definition



def configure_ecs_service_auto_scaling(
    id_prefix: str,
    service: ecs.BaseService,
    min_tasks: int,
    max_tasks: int,
    target_cpu_utilization_percent: int,
    target_memory_utilization_percent: int,
    scale_in_cooldown_seconds: int,
    scale_out_cooldown_seconds: int,
):
    """Configure how many or how few tasks should be created when auto-scaling and under what conditions."""
    scalable_target = service.auto_scale_task_count(min_capacity=min_tasks, max_capacity=max_tasks)
    scalable_target.scale_on_cpu_utilization(
        f"{id_prefix}CpuScaling",
        target_utilization_percent=target_cpu_utilization_percent,
        scale_in_cooldown=scale_in_cooldown_seconds and cdk.Duration.seconds(scale_in_cooldown_seconds),
        scale_out_cooldown=scale_out_cooldown_seconds and cdk.Duration.seconds(scale_out_cooldown_seconds),
    )
    scalable_target.scale_on_memory_utilization(
        f"{id_prefix}MemoryScaling",
        target_utilization_percent=target_memory_utilization_percent,
    )


def _configure_ecs_task_execution_role(scope: Construct, id_prefix: str, execution_role: iam.Role):
    """
    Grant the ECS task execution role necessary permissions to load docker images from ECR and start containers.

    :param scope: scope of the parent construct
    :param id_prefix: prefix for CDK construct IDs created by this function
    :param execution_role: IAM principal which will be granted access; it's the ECS execution role
    """
    execution_role.add_managed_policy(
        policy=iam.ManagedPolicy.from_managed_policy_arn(
            scope,
            id=f"{id_prefix}-fargate-execution-role-ecr-policy",
            managed_policy_arn="arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly",
        )
    )
    execution_role.add_managed_policy(
        policy=iam.ManagedPolicy.from_managed_policy_arn(
            scope,
            id=f"{id_prefix}-fargate-execution-role-ecs-policy",
            managed_policy_arn="arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy",
        )
    )


def make_task_definition(
    scope: Construct,
    id_prefix: str,
    ecs_cpu_size: int,
    ecs_memory_limit_mb: int,
    docker_image: ecs.ContainerImage,
    container_ports: List[int],
    container_env_vars_overrides: Dict[str, str],
    container_command: Optional[List[str]] = None,
) -> ecs.FargateTaskDefinition:

    stack = Stack.of(scope)

    task_definition = ecs.FargateTaskDefinition(
        scope,
        f"{id_prefix}TaskDefinition",
        cpu=ecs_cpu_size,
        memory_limit_mib=ecs_memory_limit_mb,
    )

    task_definition.add_container(
        id=f"{id_prefix}ContainerDefinition",
        logging=ecs.LogDriver.aws_logs(stream_prefix=id_prefix),
        image=docker_image,
        port_mappings=[ecs.PortMapping(container_port=port) for port in container_ports],
        environment={
            **container_env_vars_overrides,
        },
        command=container_command,
    )

    return task_definition


def make_container_port_to_target_group_mapping(
    scope: Construct,
    id_prefix: str,
    vpc: ec2.Vpc,
    health_check_port: int,
    health_check_path: str,
    container_ports: List[int],
) -> Dict[int, elbv2.ApplicationTargetGroup]:
    return {
        port: make_target_group(
            scope=scope,
            id_prefix=id_prefix,
            vpc=vpc,
            health_check_port=health_check_port,
            health_check_path=health_check_path,
            port=port,
        )
        for port in container_ports
    }


def make_target_group(
    scope: Construct,
    id_prefix: str,
    vpc: ec2.Vpc,
    health_check_port: int,
    health_check_path: str,
    port: int,
) -> elbv2.ApplicationTargetGroup:
    target_group = elbv2.ApplicationTargetGroup(
        scope,
        f"{id_prefix}TargetGroup",
        vpc=vpc,
        protocol=elbv2.ApplicationProtocol.HTTP,
        target_type=elbv2.TargetType.IP,
        port=port,
    )

    target_group.configure_health_check(
        port=str(health_check_port),
        path=health_check_path,
        protocol=elbv2.Protocol.HTTP,
    )

    return target_group


def make_service(
    scope: Construct,
    id_prefix: str,
    desired_task_count: int,
    task_definition: ecs.FargateTaskDefinition,
    ecs_cluster_in_vpc: ecs.Cluster,
    target_groups: List[elbv2.ApplicationTargetGroup],
    service_security_groups: Optional[List[ec2.SecurityGroup]] = None,
) -> ecs.FargateService:
    """
    Create a fargate service to run the ``task_definition``.

    Circuit Breaker for rolling deploy is enabled for the fargate service
    created here. The way Circuit Breaker works is it counts the number
    of tasks that have failed.

    If the number of failed AKA ``STOPPED`` tasks exceeds
    (0.5) * (desired task count), then circuit breaker kicks in and
    fails the ECS deployment. Then, circuit breaker rolls the ECS service
    back to the previous version of the service.

    .. note::

        Circuit breaker has a minimum task failure rule of 10, regardless
        of your desired count. So even if your desired count is 1, you still
        have to wait for 10 failures before the circuit breaker kicks in.

        Given that the default health check grace period is 60 seconds,
        this means you'll still be waiting at least 10 minutes (but llkely
        *much* longer) for CloudFormation and ECS to rollback a deployment
        with a broken image. This is still better than an infinite loop,
        but most of the time, it's still preferable to go into the CloudFormation
        console and manually cancel the CF update to
    """

    service = ecs.FargateService(
        scope,
        f"{id_prefix}EcsService",
        desired_count=desired_task_count,
        task_definition=task_definition,
        cluster=ecs_cluster_in_vpc,
        vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
        assign_public_ip=False,
        security_groups=service_security_groups,
        # NOTE: circuitbreaker only works with the "rolling deployment" controller
        # (as opposed to blue/green or external) Rolling deploy is the default for
        # this construct.
        circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
    )

    for target_group in target_groups:
        service.attach_to_application_target_group(target_group=target_group)

    return service


def create_or_lookup_vpc(
    scope: Construct,
    id_prefix: str,
    vpc_id: Optional[str] = None,
) -> ec2.Vpc:
    stack = Stack.of(scope)

    vpc: Optional[ec2.Vpc] = vpc_id and ec2.Vpc.from_lookup(
        scope, f"{id_prefix}Vpc", region=stack.region, vpc_id=vpc_id
    )

    vpc: ec2.Vpc = vpc or ec2.Vpc(
        scope=scope,
        id=f"{id_prefix}Vpc",
        enable_dns_support=True,
        enable_dns_hostnames=True,
    )

    return vpc

def make_load_balancer_listeners(
    scope: Construct,
    id_prefix: str,
    load_balancer_to_container_port_mappings: List[PortMapping],
    container_port_to_target_group: Dict[int, elbv2.ApplicationTargetGroup],
    load_balancer: elbv2.ApplicationLoadBalancer,
) -> Dict[int, elbv2.ApplicationListener]:
    """
    Create one load balancer listener per exposed container port (and therefore per target group).
    
    See ``make_load_balancer_listener()`` for more context.
    """
    
    listener_port_to_listener: Dict[int, elbv2.ApplicationListener] = {}
    for port_mapping in load_balancer_to_container_port_mappings:
        container_port_target_group: elbv2.ApplicationTargetGroup = container_port_to_target_group[port_mapping.container_port]
        listener_port_to_listener[port_mapping.listener_port] = make_load_balancer_listener(
            scope=scope,
            id_prefix=id_prefix,
            load_balancer=load_balancer,
            listener_port=port_mapping.listener_port,
            path_pattern=port_mapping.path_pattern,
            target_group=container_port_target_group,
        )


    return listener_port_to_listener


def make_load_balancer_listener(
    scope: Construct,
    id_prefix: str,
    listener_port: int,
    path_pattern: str,
    load_balancer: elbv2.ApplicationLoadBalancer,
    target_group: elbv2.ApplicationTargetGroup,
) -> elbv2.ApplicationListener:
    """
    Create a listener for a single port with a rule that sends all requests to the specified target group.
    
    Think of this listener as creating the mapping: ``alb:<container port> -> trg grp:<target group port>``.
    Target groups are configured with exactly one port, so the ``container_port`` parameter refers
    to the port that the listener is listening on.
    """

    listener = elbv2.ApplicationListener(
        scope,
        f"{id_prefix}Listener",
        port=listener_port,
        # TODO: get a cert and make this HTTPS
        protocol=elbv2.ApplicationProtocol.HTTP,
        load_balancer=load_balancer,
        default_action=elbv2.ListenerAction.fixed_response(
            content_type="text/html",
            message_body="Sorry mate! 404 Page not found.",
            status_code=404,
        ),
        certificates=[],
    )

    elbv2.ApplicationListenerRule(
        scope,
        f"{id_prefix}ListenerRule",
        listener=listener,
        conditions=[
            # since this is the default listener rule, match all incoming requests;
            # other listeners can override this
            elbv2.ListenerCondition.path_patterns(values=[path_pattern])
        ],
        priority=2,
        action=elbv2.ListenerAction.forward(target_groups=[target_group]),
    )

    return listener
