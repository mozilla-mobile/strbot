#!/usr/bin/env python3


import os, re, sys, time
from github import Github, GithubException, InputGitAuthor, enable_console_debug_logging
import tomlkit


DEFAULT_ORGANIZATION = "st3fan"
DEFAULT_AUTHOR_NAME = "MickeyMoz"
DEFAULT_AUTHOR_EMAIL = "sebastian@mozilla.com"

MASTER_BRANCH_NAME = "master"


# From util.py

import datetime

def ts():
    return str(datetime.datetime.now())


def get_contents(repo, path, ref):
    try:
        return repo.get_contents(path, ref=ref)
    except GithubException as e:
        pass # TODO Only return None or 404


def sync_fenix_strings(repo, fenix_major_version, author, debug, dry_run):
    #
    # Make sure the release branch for this version exists
    #

    release_branch_name = f"releases/v{fenix_major_version}.0.0" if fenix_major_version < 85 else f"releases_v{fenix_major_version}.0.0"

    #
    # Make sure the release branch is in beta. We do not sync strings to
    # released versions - that is an exception and a manual task.
    #

    release_branch = repo.get_branch(release_branch_name)

    sync_strings(repo, release_branch, "Fenix", fenix_major_version, author, debug, dry_run)


def sync_strings(repo, release_branch, product_name, major_version, author, debug, dry_run):
    print(f"{ts()} Syncing strings from {repo.full_name}:{MASTER_BRANCH_NAME} to {repo.full_name}:{release_branch.name}")

    #
    # Understand what the status of master is. We end up with
    # master_paths which are all the relevant paths in the repo that
    # are candidates to be synced. (Includes l10n.toml)
    #

    #
    # TODO Do I understand correctly that l10n-release.toml is leading
    # but not copied over? And that we do need to sync l10n.toml? That
    # file is part of the uplifts.
    #

    master_toml_contents = repo.get_contents("l10n-release.toml", ref=MASTER_BRANCH_NAME)
    master_toml = tomlkit.loads(master_toml_contents.decoded_content.decode("utf-8"))

    def android_locale(locale):
        ANDROID_COMPATIBILITY_MAPPINGS = {"he": "iw", "yi": "ji", "id": "in"}
        if locale in ANDROID_COMPATIBILITY_MAPPINGS:
            return ANDROID_COMPATIBILITY_MAPPINGS[locale]
        if matches := re.match(r"([a-z]+)-([A-Z]+)", locale):
            return f"{matches.group(1)}-r{matches.group(2)}"
        return locale

    master_paths = ["l10n.toml"]
    for locale in master_toml["locales"]:
        master_paths.append(f"app/src/main/res/values-{android_locale(locale)}/strings.xml")

    master_files = {}
    for path in master_paths:
        if (contents := get_contents(repo, path, ref=MASTER_BRANCH_NAME)) is None:
            print(f"{ts()} Could not download {path} even though it was referenced in l10n.toml")
            sys.exit(1)
        master_files[path] = contents

    #
    # Figure out what to update
    #

    changed_files = {}

    for path in master_paths:
        src = master_files[path]
        dst = get_contents(repo, path, ref=release_branch.name)
        if not dst or src.sha != dst.sha:
            print(f"{ts()} We should update {path}")
            changed_files[path] = dst

    #
    # Create a new branch and update all the files there
    #

    pr_branch_name = f"strbot/string-import-{int(time.time())}" # TODO Remove time

    repo.create_git_ref(ref=f"refs/heads/{pr_branch_name}", sha=release_branch.commit.sha)
    print(f"{ts()} Created branch {pr_branch_name} on {release_branch.commit.sha}")

    for path in changed_files.keys():
        src = master_files[path]
        print(src)
        dst = changed_files[path]
        print(dst)
        if src and dst:
            repo.update_file(src.path, f"Strings update - {path}", src.decoded_content, dst.sha, branch=pr_branch_name, author=author)
        else:
            print(f"{ts()} TODO We don't handle new files {path}")

    #
    # Create the pull request
    #

    list_of_changes = ""
    for path in changed_files.keys():
        list_of_changes += f" * `{path}`\n"

    print(f"{ts()} Creating pull request")
    pr = repo.create_pull(title=f"String sync for {product_name} v{major_version}",
                             body=f"This (automated) patch syncs strings from {product_name} `{MASTER_BRANCH_NAME}` to `{release_branch.name}`.\n\nThe following files needed an update:\n\n{list_of_changes}",
                             head=pr_branch_name, base=release_branch.name)
    print(f"{ts()} Pull request at {pr.html_url}")

if __name__ == "__main__":

    debug = os.getenv("DEBUG") is not None
    if debug:
        enable_console_debug_logging()

    github_access_token = os.getenv("GITHUB_TOKEN")
    if not github_access_token:
        print("No GITHUB_TOKEN set. Exiting.")
        sys.exit(1)

    github = Github(github_access_token)
    if github.get_user() is None:
        print("Could not get authenticated user. Exiting.")
        sys.exit(1)

    dry_run = os.getenv("DRY_RUN") == "True"

    organization = os.getenv("GITHUB_REPOSITORY_OWNER") or DEFAULT_ORGANIZATION

    ac_repo = github.get_repo(f"{organization}/android-components")
    fenix_repo = github.get_repo(f"{organization}/fenix")

    author_name = os.getenv("AUTHOR_NAME") or DEFAULT_AUTHOR_NAME
    author_email = os.getenv("AUTHOR_EMAIL") or DEFAULT_AUTHOR_EMAIL
    author = InputGitAuthor(author_name, author_email)

    sync_fenix_strings(fenix_repo, 86, author, debug, dry_run)
