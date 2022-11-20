"""
Generic OAuth utilities that can be used with any OAuth-complient provider.

Example providers: self-hosted, Auth0, Okta, Cognito, etc.
"""

from typing import List, Optional

from constructs import Construct
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk import aws_elasticloadbalancingv2_actions as elbv2_actions
from aws_cdk import aws_elasticloadbalancingv2_targets as elbv2_targets

from aws_cdk import aws_certificatemanager as acm
import aws_cdk as cdk


def create_authenticate_oidc_listener_action(
    issuer_url: str,
    client_id: str,
    client_secret: str,
    scopes: List[str],
    next_action: elbv2.ListenerAction,
    session_timeout: Optional[cdk.Duration] = None,
) -> elbv2.ListenerAction:
    """
    Create a listener action which redirects users to the Auth0 login page if the incoming request is not authenticated.

    Official AWS docs for OIDC authentication can be found here:
    https://docs.aws.amazon.com/elasticloadbalancing/latest/application/listener-authenticate-users.html#oidc-requirements

    Blog post showing how to adapt that for Auth0 here:
    https://medium.com/@sandrinodm/securing-your-applications-with-aws-alb-built-in-authentication-and-auth0-310ad84c8595

    :param issuer_url: URL indicating the issuer of incoming JWT tokens (this is an OAuth concept)
    :param client_id: client ID of the Auth0 application that facilitates the login
    :param client_secret: client secret of the Auth0 application that facilitates the login
    :param scopes: permissions required to be present in the JWT token in order to be accepted
    :param next_action: authentication isn't worth much by itself, once complete, you may want
        to perform another action, which could be passing the authenticated request to
        your target group AKA the container you wanted to reach all along
    :param session_timeout: how long until logged-in users will be asked to log in again
    """

    scopes = scopes or ["openid", "profile"]
    scope = " ".join(scope.strip() for scope in scopes)

    # TODO: is forcing a slash at the end of this a bad idea? I think we always need a slash but I could be wrong.
    issuer_url = issuer_url.strip("/") + "/"

    return elbv2.ListenerAction.authenticate_oidc(
        issuer=issuer_url,
        token_endpoint=f"{issuer_url}/oauth/token",
        user_info_endpoint=f"{issuer_url}/userinfo",
        authorization_endpoint=f"{issuer_url}/authorize",
        client_id=client_id,
        client_secret=client_secret,
        scope=scope,
        next=next_action,
        session_cookie_name="AWSELBAuthSessionCookie",
        session_timeout=session_timeout or cdk.Duration.days(1),
    )


def protect_ui_endpoint_with_auth0(
    scope: Construct,
    id_prefix: str,
    alb: elbv2.ApplicationLoadBalancer,
    url_patterns: List[str],
    target_group: elbv2.ApplicationTargetGroup,
    # auth action params; TODO, revisit how we can reduce the number of params here
    issuer_url: str,
    client_id: str,
    client_secret: str,
    scopes: List[str],
    session_timeout: Optional[cdk.Duration] = None,
    tls_cert: acm.Certificate = None,
):
    # listener = elbv2.ApplicationListener(
    #     load_balancer=alb,
    #     certificates=[
    #         elbv2.ListenerCertificate(certificate_arn=tls_cert.certificate_arn)
    #     ],
    # )
    listener: elbv2.ApplicationListener = alb.listeners[0]

    action: elbv2.ListenerAction = create_authenticate_oidc_listener_action(
        issuer_url=issuer_url,
        client_id=client_id,
        client_secret=client_secret,
        scopes=scopes,
        session_timeout=session_timeout,
        next_action=elbv2.ListenerAction.forward(target_groups=[target_group]),
    )

    elbv2.ApplicationListenerRule(
        scope,
        f"{id_prefix}LBListenerRule",
        listener=listener,
        conditions=[
            # match all requests with routes beginning with the path prefix, e.g. /api/
            elbv2.ListenerCondition.path_patterns(values=url_patterns)
        ],
        priority=1,
        action=action,
    )

    return listener
