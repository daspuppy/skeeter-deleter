import argparse
import dateutil.parser
import httpx
import magic
import os
import rich.progress
import time
import json
from atproto import CAR, Client, models
from atproto_client.request import Request
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from functools import partial
from pathlib import Path
import atproto_client.exceptions

RESUME_FILE = "resume_data.json"

def load_resume_data():
    """
    Load a JSON file (resume_data.json) containing cursors:
      {
        "last_likes_cursor": "...",
        "last_posts_cursor": "...",
        "last_reposts_cursor": "..."
      }
    If not found or invalid, returns {}.
    """
    if os.path.exists(RESUME_FILE):
        try:
            with open(RESUME_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            pass
    return {}

def save_resume_data(data: dict):
    """
    Save cursors to resume_data.json, e.g.:
      { "last_likes_cursor": "...", "last_posts_cursor": "...", "last_reposts_cursor": "..." }
    """
    with open(RESUME_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

class PostQualifier(models.AppBskyFeedDefs.FeedViewPost):
    def is_viral(self, viral_threshold) -> bool:
        if viral_threshold == 0:
            return False
        return self.post.repost_count >= viral_threshold

    def is_stale(self, stale_threshold, now) -> bool:
        if stale_threshold == 0:
            return False
        created_at = dateutil.parser.parse(self.post.record.created_at).replace(tzinfo=timezone.utc)
        return created_at <= now - timedelta(days=stale_threshold)

    def is_protected_domain(self, domains_to_protect) -> bool:
        return (
            hasattr(self.post.embed, "external")
            and any(uri in self.post.embed.external.uri for uri in domains_to_protect)
        )
        
    def is_self_liked(self) -> bool:
        # Possibly slow if many likes. We'll add a small retry for 502.
        lc = None
        while True:
            likes = self.client.safe_get_likes(self.post.uri, lc)  # uses a helper with retry
            lc = likes.cursor
            if self.client.me.did in [l.actor.did for l in likes.likes] and self.post.author.did == self.client.me.did:
                return True
            if not lc:
                break
        return False
    
    def __init__(self, client : Client):
        super(PostQualifier, self).__init__()
        self._init_PostQualifier(client)
    
    def _init_PostQualifier(self, client : Client):
        self.client = client

    def delete_like(self):
        self.client.delete_like(self.post.viewer.like)

    def remove(self):
        # remove => normal post or a repost that belongs to me
        #   if it's my post => delete_post
        #   if it's my repost => unrepost
        if self.post.author.did != self.client.me.did:
            try:
                self.client.unrepost(self.post.viewer.repost)
            except Exception as e:
                print(f"Failed to unrepost: {self.post} ({e})")
        else:
            try:
                self.client.delete_post(self.post.uri)
            except Exception as e:
                print(f"Failed to delete: {self.post.uri} ({e})")

    @staticmethod
    def to_delete(viral_threshold, stale_threshold, domains_to_protect, now, post):
        if (post.is_viral(viral_threshold) or post.is_stale(stale_threshold, now)) \
           and not post.is_protected_domain(domains_to_protect) \
           and not post.is_self_liked():
            return True
        return False

    @staticmethod
    def to_unlike(stale_threshold, now, post):
        return post.is_stale(stale_threshold, now) and not post.is_self_liked()

    @staticmethod
    def upgrade_post(client : Client, post : models.AppBskyFeedDefs.FeedViewPost):
        """
        Replaces the old .cast() method to avoid Pydantic collisions.
        Called to transform a normal feed post object into a PostQualifier instance.
        """
        post.__class__ = PostQualifier
        post._init_PostQualifier(client)
        return post

@dataclass
class Credentials:
    login: str
    password: str

    dict = asdict


class RequestCustomTimeout(Request):
    def __init__(self, timeout: httpx.Timeout = httpx.Timeout(120), *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._client = httpx.Client(follow_redirects=True, timeout=timeout)
        # Insert a 750 ms delay for every request to avoid rate-limit issues
        original_request = self._client.request
        def delayed_request(method, url, *args, **kwargs):
            time.sleep(0.75)
            return original_request(method, url, *args, **kwargs)
        self._client.request = delayed_request

class SafeClient(Client):
    """
    A subclass of atproto.Client that adds:
    - Automatic retries for certain 5xx or network errors
    """
    def safe_get_likes(self, uri, cursor=None, max_retries=3):
        backoff = 1.0
        for attempt in range(max_retries):
            try:
                return self.app.bsky.feed.get_likes(params={
                    'uri': uri,
                    'cursor': cursor,
                    'limit': 100
                })
            except (atproto_client.exceptions.NetworkError, httpx.RequestError) as e:
                print(f"safe_get_likes error on attempt {attempt+1}: {e}. Retrying...")
                time.sleep(backoff)
                backoff *= 2
        raise Exception(f"Failed to fetch likes after {max_retries} attempts.")

    def safe_get_actor_likes(self, actor, cursor=None, max_retries=3):
        backoff = 1.0
        for attempt in range(max_retries):
            try:
                return self.app.bsky.feed.get_actor_likes(params={
                    'actor': actor,
                    'cursor': cursor,
                    'limit': 100
                })
            except (atproto_client.exceptions.NetworkError, httpx.RequestError) as e:
                print(f"safe_get_actor_likes error on attempt {attempt+1}: {e}. Retrying...")
                time.sleep(backoff)
                backoff *= 2
        raise Exception(f"Failed to fetch actor_likes after {max_retries} attempts.")

    def safe_get_author_feed(self, handle, cursor=None, max_retries=3):
        backoff = 1.0
        for attempt in range(max_retries):
            try:
                return self.get_author_feed(handle, cursor=cursor, filter="from:me", limit=100)
            except (atproto_client.exceptions.NetworkError, httpx.RequestError) as e:
                print(f"safe_get_author_feed error on attempt {attempt+1}: {e}. Retrying...")
                time.sleep(backoff)
                backoff *= 2
        raise Exception(f"Failed to fetch author feed after {max_retries} attempts.")

    def safe_list_records(self, repo, collection, cursor=None, max_retries=3):
        backoff = 1.0
        for attempt in range(max_retries):
            try:
                resp = self.com.atproto.repo.list_records(params={
                    'repo': repo,
                    'collection': collection,
                    'cursor': cursor,
                    'limit': 100
                })
                return resp
            except (atproto_client.exceptions.NetworkError, httpx.RequestError) as e:
                print(f"safe_list_records error on attempt {attempt+1}: {e}. Retrying...")
                time.sleep(backoff)
                backoff *= 2
        raise Exception(f"Failed to list records from {collection} after {max_retries} attempts.")

class SkeeterDeleter:
    def gather_posts_to_unlike(self, stale_threshold, now, fixed_likes_cursor, pages_per_run, **kwargs):
        resume = load_resume_data()
        effective_cursor = fixed_likes_cursor or resume.get("last_likes_cursor")
        if effective_cursor:
            print(f"Starting from likes cursor: {effective_cursor}")

        to_unlike = []
        page_count = 0
        while True:
            if pages_per_run > 0 and page_count >= pages_per_run:
                print(f"Reached partial run limit of {pages_per_run} pages for likes. Saving and stopping.")
                break

            posts = self.client.safe_get_actor_likes(
                actor=self.client.me.handle,
                cursor=effective_cursor
            )
            casted = [PostQualifier.upgrade_post(self.client, p) for p in posts.feed]
            new_unlikes = [p for p in casted if PostQualifier.to_unlike(stale_threshold, now, p)]
            to_unlike.extend(new_unlikes)

            if not posts.cursor or posts.cursor == effective_cursor:
                break
            effective_cursor = posts.cursor
            page_count += 1
            existing = load_resume_data()
            existing["last_likes_cursor"] = effective_cursor
            save_resume_data(existing)

            if self.verbosity > 0:
                print(f"New likes cursor: {effective_cursor}")

        self.last_likes_cursor = effective_cursor
        return to_unlike

    def gather_posts_to_delete(self, viral_threshold, stale_threshold, domains_to_protect, now, pages_per_run, **kwargs):
        resume = load_resume_data()
        effective_cursor = resume.get("last_posts_cursor")
        page_count = 0
        to_delete = []
        while True:
            if pages_per_run > 0 and page_count >= pages_per_run:
                print(f"Reached partial run limit of {pages_per_run} pages for posts. Saving and stopping.")
                break

            posts = self.client.safe_get_author_feed(
                handle=self.client.me.handle,
                cursor=effective_cursor
            )
            casted = [PostQualifier.upgrade_post(self.client, p) for p in posts.feed]
            delete_test = partial(PostQualifier.to_delete, viral_threshold, stale_threshold, domains_to_protect, now)
            new_deletions = [p for p in casted if delete_test(p)]
            to_delete.extend(new_deletions)

            if not posts.cursor or posts.cursor == effective_cursor:
                break
            effective_cursor = posts.cursor
            page_count += 1
            existing = load_resume_data()
            existing["last_posts_cursor"] = effective_cursor
            save_resume_data(existing)

            if self.verbosity > 0:
                print(f"New posts cursor: {effective_cursor}")

        self.last_posts_cursor = effective_cursor
        return to_delete

    def gather_reposts_to_unrepost(self, stale_boost_limit, now, pages_per_run):
        """
        For separate handling of older reposts. We'll list from "app.bsky.feed.repost".
        We store progress in "last_reposts_cursor".
        If stale_boost_limit=0, skip entirely.
        """
        if stale_boost_limit == 0:
            return []

        resume = load_resume_data()
        effective_cursor = resume.get("last_reposts_cursor")
        if effective_cursor:
            print(f"Starting from reposts cursor: {effective_cursor}")

        reposts_to_unrepost = []
        page_count = 0
        while True:
            if pages_per_run > 0 and page_count >= pages_per_run:
                print(f"Reached partial run limit of {pages_per_run} pages for reposts. Saving and stopping.")
                break

            resp = self.client.safe_list_records(
                repo=self.client.me.handle,
                collection="app.bsky.feed.repost",
                cursor=effective_cursor
            )
            if not hasattr(resp, "records"):
                break
            if len(resp.records) == 0:
                break

            for r in resp.records:
                created_str = r.value.created_at
                created_at = dateutil.parser.isoparse(created_str)
                if created_at <= now - timedelta(days=stale_boost_limit):
                    reposts_to_unrepost.append(r.value.uri)
                else:
                    pass

            if not resp.cursor or resp.cursor == effective_cursor:
                break
            effective_cursor = resp.cursor
            page_count += 1
            existing = load_resume_data()
            existing["last_reposts_cursor"] = effective_cursor
            save_resume_data(existing)

            if self.verbosity > 0:
                print(f"New reposts cursor: {effective_cursor}")

        self.last_reposts_cursor = effective_cursor
        return reposts_to_unrepost

    def batch_unlike_posts(self) -> None:
        if self.verbosity > 0:
            print(f"Unliking {len(self.to_unlike)} post{'' if len(self.to_unlike) == 1 else 's'}")
        for post in rich.progress.track(self.to_unlike, description="Unliking posts"):
            if self.verbosity == 2:
                print(f"Unliking: {post.post.record.post} by {post.post.author.handle}, CID: {post.post.cid}")
            post.delete_like()

    def batch_delete_posts(self) -> None:
        if self.verbosity > 0:
            print(f"Deleting {len(self.to_delete)} post{'' if len(self.to_delete) == 1 else 's'}")
        for post in rich.progress.track(self.to_delete, description="Deleting posts"):
            if self.verbosity == 2:
                print(f"Deleting: {post.post.record.post} on {post.post.record.created_at}, CID: {post.post.cid}")
            post.remove()

    def batch_unrepost(self, repost_uris):
        if self.verbosity > 0:
            print(f"Undoing {len(repost_uris)} older repost{'' if len(repost_uris) == 1 else 's'}")
        for uri in rich.progress.track(repost_uris, description="Unreposting"):
            try:
                self.client.unrepost(uri)
            except Exception as e:
                print(f"Failed to unrepost: {uri} => {e}")
            
    def archive_repo(self, now, **kwargs):
        repo = self.client.com.atproto.sync.get_repo(params={'did': self.client.me.did})
        car = CAR.from_bytes(repo)
        clean_user_did = self.client.me.did.replace(":", "_")
        Path(f"archive/{clean_user_did}/_blob/").mkdir(parents=True, exist_ok=True)
        print("Archiving posts...")
        clean_now = now.isoformat().replace(':','_')
        with open(f"archive/{clean_user_did}/bsky-archive-{clean_now}.car", "wb") as f:
            f.write(repo)

        cursor = None
        print("Downloading and archiving media...")
        blob_cids = []
        while True:
            try:
                blob_page = self.client.com.atproto.sync.list_blobs(params={'did': self.client.me.did, 'cursor': cursor})
            except Exception as e:
                print(f"Error listing blobs: {e}")
                break
            blob_cids.extend(blob_page.cids)
            cursor = blob_page.cursor
            if not cursor:
                break
        for cid in rich.progress.track(blob_cids, description="Downloading blobs"):
            try:
                blob = self.client.com.atproto.sync.get_blob(params={'cid': cid, 'did': self.client.me.did})
            except Exception as e:
                print(f"Error fetching blob {cid}: {e}")
                continue
            file_type = magic.from_buffer(blob, 2048)
            ext = ".jpeg" if file_type == "image/jpeg" else ""
            file_path = f"archive/{clean_user_did}/_blob/{cid}{ext}"
            try:
                with open(file_path, "wb") as f:
                    if self.verbosity == 2:
                        print(f"Saving blob {cid}{ext}")
                    f.write(blob)
            except Exception as ee:
                print(f"Error writing blob {cid}{ext} => {ee}")

    def __init__(
        self,
        credentials,
        viral_threshold=0,
        stale_threshold=0,
        domains_to_protect=[],
        fixed_likes_cursor=None,
        verbosity=0,
        autodelete=False,
        pages_per_run=100,
        stale_boost_limit=0
    ):
        """
        stale_boost_limit: # of days after which to un-repost older reposts. 0 = skip.
        """
        self.client = SafeClient(request=RequestCustomTimeout())
        self.client.login(**credentials.dict())

        self.verbosity = verbosity
        self.autodelete = autodelete

        now = datetime.now(timezone.utc)
        params = {
            'viral_threshold': viral_threshold,
            'stale_threshold': stale_threshold,
            'domains_to_protect': domains_to_protect,
            'fixed_likes_cursor': fixed_likes_cursor,
            'now': now,
            'pages_per_run': pages_per_run
        }

        # 1) Archive
        self.archive_repo(**params)

        # 2) Gather likes to unlike
        self.to_unlike = self.gather_posts_to_unlike(**params)
        print(f"Found {len(self.to_unlike)} post{'' if len(self.to_unlike) == 1 else 's'} to unlike.")

        # 3) Gather normal posts to delete
        self.to_delete = self.gather_posts_to_delete(**params)
        print(f"Found {len(self.to_delete)} post{'' if len(self.to_delete) == 1 else 's'} to delete.")

        # 4) Gather older reposts if stale_boost_limit > 0
        self.reposts_to_unrepost = self.gather_reposts_to_unrepost(stale_boost_limit, now, pages_per_run)
        if stale_boost_limit > 0:
            print(f"Found {len(self.reposts_to_unrepost)} older repost{'' if len(self.reposts_to_unrepost) == 1 else 's'} to undo.")

    def unlike(self):
        n_unlike = len(self.to_unlike)
        if n_unlike:
            prompt = None
            while not self.autodelete and prompt not in ("Y", "n"):
                prompt = input(
                    f"\nProceed to unlike {n_unlike} post{'' if n_unlike == 1 else 's'}?"
                    " WARNING: THIS IS DESTRUCTIVE AND CANNOT BE UNDONE. Y/n: "
                )
            if self.autodelete or prompt == "Y":
                self.batch_unlike_posts()

    def delete(self):
        n_delete = len(self.to_delete)
        if n_delete:
            prompt = None
            while not self.autodelete and prompt not in ("Y", "n"):
                prompt = input(
                    f"\nProceed to delete {n_delete} post{'' if n_delete == 1 else 's'}?"
                    " WARNING: THIS IS DESTRUCTIVE AND CANNOT BE UNDONE. Y/n: "
                )
            if self.autodelete or prompt == "Y":
                self.batch_delete_posts()

    def unrepost(self):
        """
        Actually undo older reposts. If no reposts_to_unrepost, skip.
        """
        n_reposts = len(self.reposts_to_unrepost)
        if n_reposts:
            prompt = None
            while not self.autodelete and prompt not in ("Y", "n"):
                prompt = input(
                    f"\nProceed to undo {n_reposts} old repost{'' if n_reposts == 1 else 's'}?"
                    " WARNING: THIS IS DESTRUCTIVE AND CANNOT BE UNDONE. Y/n: "
                )
            if self.autodelete or prompt == "Y":
                self.batch_unrepost(self.reposts_to_unrepost)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument("-u", "--username", required=True, help="Bluesky username")
    parser.add_argument("-p", "--password", required=True, help="Bluesky password")

    parser.add_argument("-l", "--max-reposts", type=int, default=0,
                        help="Max reposts before deletion (0 to disable). This is for normal posts only.")
    parser.add_argument("-s", "--stale-limit", type=int, default=0,
                        help="Age in days that marks a post or like stale (0 to disable).")
    parser.add_argument("-b", "--stale-boost-limit", type=int, default=0,
                        help="Age in days for older reposts. Reposts older than this limit will be undone. 0=skip.")
    parser.add_argument("-d", "--domains-to-protect", default="",
                        help="Comma separated list of domains to protect. Default empty.")
    parser.add_argument("-c", "--fixed-likes-cursor", default="",
                        help="Manually set a cursor to skip older likes. Default empty.")
    parser.add_argument("-P", "--pages-per-run", type=int, default=100,
                        help="How many pages to process per run (for likes, posts, and reposts). Default=100")
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument("-v", "--verbose", action="store_true",
                           help="Show more information about what is happening.")
    verbosity.add_argument("-vv", "--very-verbose", action="store_true",
                           help="Show granular information about what is happening.")
    parser.add_argument("-y", "--yes", action="store_true", default=False,
                        help="Skip confirmation prompts (automation mode).")

    args = parser.parse_args()

    domains_list = [s.strip() for s in args.domains_to_protect.split(",") if s.strip()]
    verbosity_level = 0
    if args.verbose:
        verbosity_level = 1
    elif args.very_verbose:
        verbosity_level = 2

    creds = Credentials(args.username, args.password)
    sd = SkeeterDeleter(
        credentials=creds,
        viral_threshold=args.max_reposts,
        stale_threshold=args.stale_limit,
        stale_boost_limit=args.stale_boost_limit,
        domains_to_protect=domains_list,
        fixed_likes_cursor=args.fixed_likes_cursor or None,
        verbosity=verbosity_level,
        autodelete=args.yes,
        pages_per_run=args.pages_per_run
    )

    # Runs the normal unliking & deleting
    sd.unlike()
    sd.delete()
    # Then asks about older reposts
    sd.unrepost()
