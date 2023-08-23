import jwt
from bson import ObjectId
from fastapi import HTTPException, status

from config import GOLDEN_SQL_REF_COL, QUERY_RESPONSE_REF_COL, USER_COL, auth_settings
from database.mongo import MongoDB
from modules.organization.models.entities import Organization
from modules.organization.service import OrganizationService
from modules.query.service import QueryService
from modules.user.models.entities import User
from modules.user.service import UserService

user_service = UserService()
org_service = OrganizationService()
query_service = QueryService()

test_user = User(
    email="test@dataherald.com",
    email_verified=True,
    name="Test User",
    organization_id=ObjectId(b"foo-bar-quux"),
)

test_organization = Organization(
    _id=ObjectId(b"foo-bar-quux"),
    name="Test Org",
    db_alias="v2_real_estate",
    slack_workspace_id="test_slack_id",
)


class VerifyToken:
    """Does all the token verification using PyJWT"""

    def __init__(self, token):
        self.token = token

        # This gets the JWKS from a given URL and does processing so you can
        # use any of the keys available
        jwks_url = f"https://{auth_settings.auth0_domain}/.well-known/jwks.json"
        self.jwks_client = jwt.PyJWKClient(jwks_url)

    def verify(self):
        # return mock authentication data
        if not auth_settings.auth_enabled:
            return {
                auth_settings.auth0_issuer + "email": test_user.email,  # placeholder
                "iss": auth_settings.auth0_issuer,
                "sub": "foo",
                "aud": auth_settings.auth0_audience,
                "iat": "",
                "exp": "",
                "azp": "",
                "scope": "openid profile email offline_access",
                "gty": "client-credentials",
            }
        # This gets the 'kid' from the passed token
        try:
            self.signing_key = self.jwks_client.get_signing_key_from_jwt(self.token).key
        except jwt.exceptions.PyJWKClientError as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=error.__str__()
            ) from jwt.exceptions.PyJWKClientError
        except jwt.exceptions.DecodeError as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=error.__str__()
            ) from jwt.exceptions.DecodeError
        try:
            payload = jwt.decode(
                self.token,
                self.signing_key,
                algorithms=auth_settings.auth0_algorithms,
                audience=auth_settings.auth0_audience,
                issuer=auth_settings.auth0_issuer,
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
            ) from Exception
        return payload


class Authorize:
    def user(self, payload: dict) -> User:
        if not auth_settings.auth_enabled:
            return test_user

        email = payload[auth_settings.auth0_issuer + "email"]
        user = user_service.get_user_by_email(email)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized User"
            )
        return user

    def query_in_organization(self, query_id: str, org_id: str):
        self._item_in_organization(
            QUERY_RESPONSE_REF_COL, query_id, org_id, key="query_response_id"
        )

    def user_in_organization(self, user_id: str, org_id: str):
        self._item_in_organization(USER_COL, user_id, org_id)

    def golden_sql_in_organization(self, golden_sql_id: str, org_id: str):
        self._item_in_organization(GOLDEN_SQL_REF_COL, golden_sql_id, org_id)

    def user_and_get_org_id(self, payload) -> ObjectId:
        user = self.user(payload)
        return self._get_organization_id_with_user(user)

    def _get_organization_id_with_user(self, user: User) -> ObjectId:
        if not auth_settings.auth_enabled:
            return test_organization.id

        organization = org_service.get_organization(str(user.organization_id))
        if not organization:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User does not belong to an Organization",
            )
        return ObjectId(organization.id)

    def _item_in_organization(
        self, collection: str, id: str, org_id: str, key: str = None
    ):
        if not auth_settings.auth_enabled:
            return

        if key:
            item = MongoDB.find_one(collection, {key: id})
        else:
            item = MongoDB.find_by_id(collection, id)
        if not item:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        if org_id != str(item.organization_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)