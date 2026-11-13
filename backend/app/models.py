"""Request/response models."""
from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

DEFAULT_PORT = 445


# Hostname, IPv4 or IPv6 literal. Anything else has no business in a UNC path.
_HOST_RE = re.compile(r"^[A-Za-z0-9._:\-\[\]%]{1,253}$")


def _clean_host(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("Host or IP address is required.")
    # Reject a pasted URL rather than silently connecting somewhere odd.
    if "/" in v or "\\" in v:
        raise ValueError("Enter just the host or IP, without smb:// or a path.")
    if not _HOST_RE.fullmatch(v):
        raise ValueError("Host contains characters that are not valid in a "
                         "hostname or IP address.")
    return v


def _clean_share(v: str) -> str:
    v = v.strip().strip("/\\")
    # A separator inside the share name would change which share (or which
    # server path) the UNC resolves to.
    if any(c in v for c in '/\\') or any(ord(c) < 32 for c in v):
        raise ValueError("Share name may not contain slashes.")
    return v


class LoginRequest(BaseModel):
    password: str = Field(max_length=1024)


class ServerCreate(BaseModel):
    name: str = ""
    host: str
    port: int = DEFAULT_PORT
    share_name: str = Field(default="", alias="shareName")
    username: str = ""
    password: str = ""
    domain: str = ""
    save_credentials: bool = Field(default=True, alias="saveCredentials")

    model_config = {"populate_by_name": True}

    @field_validator("host")
    @classmethod
    def _host_required(cls, v: str) -> str:
        return _clean_host(v)

    @field_validator("share_name")
    @classmethod
    def _share_clean(cls, v: str) -> str:
        return _clean_share(v)

    @field_validator("port")
    @classmethod
    def _port_range(cls, v: int) -> int:
        if not 1 <= v <= 65535:
            raise ValueError("Port must be between 1 and 65535.")
        return v


class ServerUpdate(BaseModel):
    name: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    share_name: Optional[str] = Field(default=None, alias="shareName")
    username: Optional[str] = None
    password: Optional[str] = None
    domain: Optional[str] = None
    save_credentials: Optional[bool] = Field(default=None, alias="saveCredentials")

    model_config = {"populate_by_name": True}

    @field_validator("host")
    @classmethod
    def _host_valid(cls, v: Optional[str]) -> Optional[str]:
        return v if v is None else _clean_host(v)

    @field_validator("share_name")
    @classmethod
    def _share_clean(cls, v: Optional[str]) -> Optional[str]:
        return v if v is None else _clean_share(v)

    @field_validator("port")
    @classmethod
    def _port_range(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and not 1 <= v <= 65535:
            raise ValueError("Port must be between 1 and 65535.")
        return v


class ConnectRequest(BaseModel):
    """A one-off password, for profiles that don't save credentials."""
    password: Optional[str] = None


class MkdirRequest(BaseModel):
    server_id: str = Field(alias="serverId")
    parent: str
    name: str
    model_config = {"populate_by_name": True}


class RenameRequest(BaseModel):
    server_id: str = Field(alias="serverId")
    path: str
    new_name: str = Field(alias="newName")
    model_config = {"populate_by_name": True}


class TransferRequest(BaseModel):
    server_id: str = Field(alias="serverId")
    sources: list[str]
    destination: str
    model_config = {"populate_by_name": True}


class DeleteRequest(BaseModel):
    server_id: str = Field(alias="serverId")
    paths: list[str]
    model_config = {"populate_by_name": True}


class Preferences(BaseModel):
    default_view_mode: Literal["list", "grid"] = Field(default="list", alias="defaultViewMode")
    default_sort_field: Literal["name", "dateModified", "size", "type"] = \
        Field(default="name", alias="defaultSortField")
    default_sort_direction: Literal["ascending", "descending"] = \
        Field(default="ascending", alias="defaultSortDirection")
    recursive_search: bool = Field(default=False, alias="recursiveSearch")
    show_hidden_files: bool = Field(default=False, alias="showHiddenFiles")
    recovery_link_name: str = Field(default="", alias="recoveryLinkName")
    recovery_link_url: str = Field(default="", alias="recoveryLinkUrl",
                                   max_length=2048)

    model_config = {"populate_by_name": True}

    @field_validator("recovery_link_url")
    @classmethod
    def _http_only(cls, v: str) -> str:
        v = v.strip()
        # The UI opens this in a new tab; a javascript: or data: URL there
        # would run in this app's origin.
        if v and not v.lower().startswith(("http://", "https://")):
            raise ValueError("Recovery link must start with http:// or https://")
        return v
