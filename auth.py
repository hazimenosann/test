import os
import sys

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

import config


def get_gmail_service():
    """Authenticate with Gmail API and return a service object."""
    creds = None

    if os.path.exists(config.TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(config.TOKEN_FILE, config.GMAIL_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                os.remove(config.TOKEN_FILE)
                creds = None

        if not creds:
            if not os.path.exists(config.CREDENTIALS_FILE):
                print(
                    "エラー: credentials.json が見つかりません。\n"
                    "README.md の「Googleアカウント認証の設定」セクションを参照して\n"
                    f"OAuth2 認証情報を {config.CREDENTIALS_FILE} に配置してください。"
                )
                sys.exit(1)

            flow = InstalledAppFlow.from_client_secrets_file(
                config.CREDENTIALS_FILE, config.GMAIL_SCOPES
            )
            creds = flow.run_local_server(port=0)

        with open(config.TOKEN_FILE, "w") as token_file:
            token_file.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)
