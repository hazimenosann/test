#!/usr/bin/env python3
"""
Gmail 領収書ダウンローダー
電子帳簿保存法（2022年改正）対応

使い方:
  python gmail_receipt_downloader.py               # 全期間
  python gmail_receipt_downloader.py --months 3    # 直近3ヶ月
  python gmail_receipt_downloader.py --after 2024/01/01
  python gmail_receipt_downloader.py --dry-run     # ファイル保存なし（確認用）
  python gmail_receipt_downloader.py --verify-only # 整合性チェックのみ
"""

import argparse
import datetime
import logging
import os
import sys

import auth
import config
import file_organizer
import gmail_client
import index_manager
import integrity
import metadata_extractor
import pdf_converter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(description="Gmail 領収書ダウンローダー（電子帳簿保存法対応）")
    parser.add_argument(
        "--months", type=int, default=None,
        help="直近N ヶ月分のみ処理（例: --months 3）"
    )
    parser.add_argument(
        "--after", type=str, default=None,
        help="この日付以降のメールを処理（YYYY/MM/DD 形式）"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="ファイルを保存せず処理内容を表示するだけ"
    )
    parser.add_argument(
        "--verify-only", action="store_true",
        help="整合性ハッシュを検証してレポートを表示するだけ"
    )
    return parser.parse_args()


def compute_after_date(args):
    """Return the 'after' date string for Gmail query, or None."""
    if args.after:
        return args.after
    if args.months:
        target = datetime.date.today() - datetime.timedelta(days=30 * args.months)
        return target.strftime("%Y/%m/%d")
    return config.SEARCH_AFTER_DATE


def process_attachment(service, msg_id, attachment, headers, received_date,
                       processed_ids, dry_run):
    """Process a single email attachment (PDF or image)."""
    data = attachment["data"]
    mime = attachment["mime_type"]
    subject = headers.get("subject", "")
    sender = headers.get("from", "")
    email_message_id = headers.get("message-id", "")

    # Convert non-PDF to PDF
    if not pdf_converter.is_pdf_bytes(data):
        if mime.startswith("image/"):
            logger.info("    画像→PDF 変換中...")
            data = pdf_converter.image_to_pdf(data)
            source_type = "image_converted"
        else:
            # Could be HTML misnamed as pdf
            try:
                html_str = data.decode("utf-8", errors="replace")
                data = pdf_converter.html_to_pdf(html_str)
                source_type = "html_converted"
            except Exception as e:
                logger.warning(f"    PDF 変換失敗: {e}")
                return None
    else:
        source_type = "pdf_attachment"

    # Extract metadata via Claude API
    body_text = gmail_client.extract_plain_body(
        service.users().messages().get(userId="me", id=msg_id, format="full").execute()["payload"]
    ) if not dry_run else subject
    meta = metadata_extractor.extract_metadata_with_claude(
        subject, body_text, sender, received_date
    )

    date = meta["date"]
    amount = meta["amount"]
    counterparty = meta["counterparty"]
    needs_review = (amount == "金額不明" or counterparty == "")

    filename = metadata_extractor.build_filename(date, amount, counterparty)
    rel_path = os.path.join(
        str(date.year), f"{date.year}-{date.month:02d}", filename
    )

    logger.info(f"    → {rel_path}  ({source_type})")

    if dry_run:
        return {"status": "dry_run", "path": rel_path}

    out_path = file_organizer.get_output_path(config.OUTPUT_DIR, date, filename)
    out_path = file_organizer.resolve_filename_conflict(out_path)
    final_filename = os.path.basename(out_path)
    final_rel_path = os.path.relpath(out_path, config.OUTPUT_DIR)

    file_organizer.write_pdf(out_path, data)

    sha256 = integrity.compute_sha256(out_path)
    saved_at = integrity.generate_timestamp()
    integrity.save_hash(config.HASH_LOG_PATH, final_rel_path, sha256, saved_at)

    record = index_manager.build_record(
        date=date,
        amount=amount,
        counterparty=counterparty,
        filename=final_filename,
        filepath=final_rel_path,
        subject=subject,
        email_from=sender,
        email_message_id=email_message_id,
        gmail_msg_id=msg_id,
        saved_at=saved_at,
        sha256=sha256,
        source_type=source_type,
        needs_review=needs_review,
    )
    index_manager.append_to_index(config.INDEX_CSV_PATH, record)
    file_organizer.save_processed_id(config.PROCESSED_IDS_PATH, msg_id)

    return {"status": "saved", "path": out_path}


def process_html_body(html_body, msg_id, headers, received_date, dry_run):
    """Convert HTML email body to PDF and save."""
    subject = headers.get("subject", "")
    sender = headers.get("from", "")
    email_message_id = headers.get("message-id", "")

    from bs4 import BeautifulSoup
    plain_text = BeautifulSoup(html_body, "lxml").get_text(separator="\n")

    meta = metadata_extractor.extract_metadata_with_claude(
        subject, plain_text, sender, received_date
    )
    date = meta["date"]
    amount = meta["amount"]
    counterparty = meta["counterparty"]
    needs_review = (amount == "金額不明" or counterparty == "")

    filename = metadata_extractor.build_filename(date, amount, counterparty)
    rel_path = os.path.join(str(date.year), f"{date.year}-{date.month:02d}", filename)

    logger.info(f"    → {rel_path}  (html_converted)")

    if dry_run:
        return {"status": "dry_run", "path": rel_path}

    try:
        pdf_bytes = pdf_converter.html_to_pdf(html_body)
    except Exception as e:
        logger.warning(f"    HTML→PDF 変換失敗: {e}")
        return None

    out_path = file_organizer.get_output_path(config.OUTPUT_DIR, date, filename)
    out_path = file_organizer.resolve_filename_conflict(out_path)
    final_filename = os.path.basename(out_path)
    final_rel_path = os.path.relpath(out_path, config.OUTPUT_DIR)

    file_organizer.write_pdf(out_path, pdf_bytes)

    sha256 = integrity.compute_sha256(out_path)
    saved_at = integrity.generate_timestamp()
    integrity.save_hash(config.HASH_LOG_PATH, final_rel_path, sha256, saved_at)

    record = index_manager.build_record(
        date=date,
        amount=amount,
        counterparty=counterparty,
        filename=final_filename,
        filepath=final_rel_path,
        subject=subject,
        email_from=sender,
        email_message_id=email_message_id,
        gmail_msg_id=msg_id,
        saved_at=saved_at,
        sha256=sha256,
        source_type="html_converted",
        needs_review=needs_review,
    )
    index_manager.append_to_index(config.INDEX_CSV_PATH, record)
    file_organizer.save_processed_id(config.PROCESSED_IDS_PATH, msg_id)

    return {"status": "saved", "path": out_path}


def run_verify_only():
    """Run integrity verification and print report."""
    print("\n=== 整合性チェック ===")
    results = integrity.verify_all_hashes(config.HASH_LOG_PATH, config.OUTPUT_DIR)
    if not results:
        print("ハッシュログが見つかりません。")
        return

    ok = [r for r in results if r["status"] == "ok"]
    modified = [r for r in results if r["status"] == "MODIFIED"]
    missing = [r for r in results if r["status"] == "MISSING"]

    print(f"正常: {len(ok)} ファイル")
    for r in modified:
        print(f"  [改ざん検知] {r['file']}")
    for r in missing:
        print(f"  [ファイル不明] {r['file']}")

    if not modified and not missing:
        print("すべてのファイルが正常です。")


def main():
    args = parse_args()

    if args.verify_only:
        run_verify_only()
        return

    logger.info("Gmail 認証中...")
    service = auth.get_gmail_service()

    after_date = compute_after_date(args)
    if after_date:
        logger.info(f"対象期間: {after_date} 以降")

    if args.dry_run:
        logger.info("--- DRY RUN モード（ファイルは保存されません）---")

    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    processed_ids = file_organizer.load_processed_ids(config.PROCESSED_IDS_PATH)
    logger.info(f"既処理メール数: {len(processed_ids)}")

    # Gather all unique message IDs
    logger.info("メール検索中...")
    msg_ids = gmail_client.search_receipt_messages(
        service, config.GMAIL_SEARCH_QUERIES, after_date=after_date
    )
    logger.info(f"対象メール数: {len(msg_ids)}")

    saved_count = 0
    skipped_count = 0
    error_count = 0

    for i, msg_id in enumerate(msg_ids, 1):
        if file_organizer.is_duplicate(msg_id, processed_ids):
            skipped_count += 1
            continue

        logger.info(f"[{i}/{len(msg_ids)}] メール処理中: {msg_id}")

        try:
            detail = gmail_client.get_message_detail(service, msg_id)
            payload = detail["payload"]
            headers = gmail_client.extract_headers(payload)

            subject = headers.get("subject", "(件名なし)")
            sender = headers.get("from", "")
            logger.info(f"  件名: {subject}")
            logger.info(f"  送信者: {sender}")

            received_date = metadata_extractor.parse_received_date(headers.get("date"))

            # Try PDF/image attachments first
            attachments = gmail_client.extract_attachments(service, msg_id, payload)
            if attachments:
                for att in attachments:
                    result = process_attachment(
                        service, msg_id, att, headers, received_date, processed_ids, args.dry_run
                    )
                    if result:
                        saved_count += 1
                        if not args.dry_run:
                            processed_ids.add(msg_id)
                # Skip HTML processing if we handled attachments
                continue

            # Fallback: HTML email body
            html_body = gmail_client.extract_html_body(payload)
            if html_body:
                result = process_html_body(html_body, msg_id, headers, received_date, args.dry_run)
                if result:
                    saved_count += 1
                    if not args.dry_run:
                        processed_ids.add(msg_id)
                continue

            # No receipt content found
            logger.info("  領収書コンテンツが見つかりませんでした。スキップします。")
            skipped_count += 1

        except Exception as e:
            logger.error(f"  処理エラー ({msg_id}): {e}")
            error_count += 1

    print("\n=== 処理完了 ===")
    print(f"保存: {saved_count} 件")
    print(f"スキップ（既処理・コンテンツなし）: {skipped_count} 件")
    print(f"エラー: {error_count} 件")
    if not args.dry_run and saved_count > 0:
        print(f"保存先: {config.OUTPUT_DIR}")
        print(f"インデックス: {config.INDEX_CSV_PATH}")


if __name__ == "__main__":
    main()
