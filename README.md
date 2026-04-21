# Gmail 領収書ダウンローダー

Gmailに届いた領収書・請求書を**電子帳簿保存法（2022年改正）**に則ってダウンロードし、月別フォルダに整理するツールです。

## 機能

- Gmail から領収書・請求書メールを自動検索
- PDF添付・HTML本文・画像添付（PNG/JPG）の3形式に対応
- Claude API で日付・金額・取引先を自動抽出
- 電子帳簿保存法準拠のファイル名: `YYYYMMDD_金額_取引先.pdf`
- 月別フォルダ構造: `receipts/YYYY/YYYY-MM/`
- CSV インデックス（Excel で開ける UTF-8 BOM 付き）
- SHA-256 ハッシュによる改ざん検知（真実性確保）
- 重複ダウンロード防止

## セットアップ

### 1. 依存ライブラリのインストール

```bash
pip install -r requirements.txt
```

日本語フォントが必要です（WeasyPrint 使用）:

```bash
# Ubuntu / Debian
sudo apt-get install fonts-noto-cjk

# macOS
brew install --cask font-noto-sans-cjk
```

### 2. Google Cloud Console での認証情報作成

1. [Google Cloud Console](https://console.cloud.google.com/) にアクセス
2. 新しいプロジェクトを作成（例: "Gmail Receipt Organizer"）
3. **APIs & Services > Enable APIs** から **Gmail API** を有効化
4. **APIs & Services > Credentials > Create Credentials > OAuth client ID** を選択
   - アプリケーションの種類: **デスクトップアプリ**
5. ダウンロードした JSON ファイルを `credentials.json` にリネームして、このディレクトリに配置
6. **OAuth 同意画面 > テストユーザー** に自分の Gmail アドレスを追加

### 3. Anthropic API キーの設定

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

または `.env` ファイルを使用してください（`.gitignore` で除外済み）。

## 使い方

```bash
# 全期間の領収書をダウンロード
python gmail_receipt_downloader.py

# 直近3ヶ月分のみ
python gmail_receipt_downloader.py --months 3

# 指定日以降のみ
python gmail_receipt_downloader.py --after 2024/01/01

# ドライラン（ファイル保存なし、動作確認用）
python gmail_receipt_downloader.py --dry-run

# ハッシュ整合性チェック（改ざん検知）
python gmail_receipt_downloader.py --verify-only
```

初回実行時はブラウザが開き、Google アカウントへのアクセス許可を求められます。

## 出力ファイル構成

```
receipts/
├── 2024/
│   ├── 2024-01/
│   │   ├── 20240115_12800_Amazon.co.jp.pdf
│   │   └── 20240128_5500_株式会社○○.pdf
│   └── 2024-02/
│       └── 20240210_3300_楽天市場.pdf
├── receipt_index.csv      # 検索用インデックス（電子帳簿保存法対応）
└── integrity_hashes.json  # SHA-256 ハッシュログ（真実性確保）
```

## 電子帳簿保存法 対応状況

| 要件 | 対応内容 |
|------|----------|
| ファイル命名規則 | `取引年月日_金額_取引先.pdf` |
| 検索要件 | `receipt_index.csv` で日付・金額・取引先の範囲検索が可能 |
| 真実性確保 | SHA-256 ハッシュで改ざん検知（`--verify-only` で確認） |
| 訂正削除の防止 | Gmail 読み取り専用スコープ使用 |
| 可視性確保 | 標準 PDF 形式で即時閲覧可能 |

> **注意**: タイムスタンプ要件（第三者認定タイムスタンプ）が必要な場合は、別途タイムスタンプサービス（RFC 3161 対応）との連携が必要です。本ツールはハッシュログ方式を採用しており、**訂正削除防止に関する事務処理規程**を整備している事業者向けの構成です。

## 検索インデックス（receipt_index.csv）の列

| 列名 | 内容 |
|------|------|
| `receipt_date` | 取引日（YYYY-MM-DD） |
| `amount` | 金額（数値） |
| `counterparty` | 取引先名 |
| `filename` | ファイル名 |
| `filepath` | receipts/ からの相対パス |
| `email_subject` | 元メールの件名 |
| `sha256` | ファイルの SHA-256 ハッシュ |
| `source_type` | `pdf_attachment` / `html_converted` / `image_converted` |
| `needs_review` | 要確認フラグ（金額・取引先が不明な場合） |

## 注意事項

- `credentials.json` および `token.json` は **絶対にコミットしないでください**（`.gitignore` で除外済み）
- `receipts/` フォルダも `.gitignore` で除外済みです
- Gmail の読み取り専用スコープ（`gmail.readonly`）のみ使用します
