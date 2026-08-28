"""Request/response models."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

DEFAULT_PORT = 445


class LoginRequest(BaseModel):
    password: str


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
        v = v.strip()
        if not v:
            raise ValueError("Host or IP address is required.")
        # Reject a pasted URL rather than silently connecting somewhere odd.
        if "/" in v or "\\" in v:
            raise ValueError("Enter just the host or IP, without smb:// or a path.")
        return v

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
    recovery_link_url: str = Field(default="", alias="recoveryLinkUrl")

    model_config = {"populate_by_name": True}
