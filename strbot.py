#!/usr/bin/env python3


import datetime, os, re, sys, time

import github
import tomlkit


DEFAULT_REPOSITORY_OWNER = "st3fan"
DEFAULT_AUTHOR_NAME = "MickeyMoz"
DEFAULT_AUTHOR_EMAIL = "sebastian@mozilla.com"

MASTER_BRANCH_NAME = "master"


def ts():
    return str(datetime.datetime.now())


def get_contents(repo, path, ref):
    """Wrapper around get_contents that returns None instead of throwing on a 404"""
    try:
        return repo.get_contents(path, ref=ref)
    except github.UnknownObjectException as e:
        pass


def android_locale(locale):
    """Convert the given Pontoon locale to the code Android uses"""
    ANDROID_COMPATIBILITY_MAPPINGS = {"he": "iw", "yi": "ji", "id": "in"}
    if locale in ANDROID_COMPATIBILITY_MAPPINGS:
        return ANDROID_COMPATIBILITY_MAPPINGS[locale]
    if matches := re.match(r"([a-z]+)-([A-Z]+)", locale):
        return f"{matches.group(1)}-r{matches.group(2)}"
    return locale


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

    version_contents = repo.get_contents("version.txt", ref=release_branch_name)
    version = version_contents.decoded_content.decode("utf-8")
    if "-beta." not in version:
        print(f"{ts()} Not syncing strings for <{release_branch_name}> since it is not beta")
        return

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
        dst = changed_files[path]
        if dst:
            print(f"{ts()} Updating {path}")
            repo.update_file(src.path, f"Strings update - {path}", src.decoded_content,
                             dst.sha, branch=pr_branch_name, author=author)
        else:
            print(f"{ts()} Creating {path}")
            repo.create_file(src.path, f"Strings update - {path}", src.decoded_content,
                             branch=pr_branch_name)

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
        github.enable_console_debug_logging()

    github_access_token = os.getenv("GITHUB_TOKEN")
    if not github_access_token:
        print("No GITHUB_TOKEN set. Exiting.")
        sys.exit(1)

    gh = github.Github(github_access_token)
    if gh.get_user() is None:
        print("Could not get authenticated user. Exiting.")
        sys.exit(1)

    dry_run = os.getenv("DRY_RUN") == "True"

    organization = os.getenv("GITHUB_REPOSITORY_OWNER") or DEFAULT_REPOSITORY_OWNER

    ac_repo = gh.get_repo(f"{organization}/android-components")
    fenix_repo = gh.get_repo(f"{organization}/fenix")

    author_name = os.getenv("AUTHOR_NAME") or DEFAULT_AUTHOR_NAME
    author_email = os.getenv("AUTHOR_EMAIL") or DEFAULT_AUTHOR_EMAIL
    author = github.InputGitAuthor(author_name, author_email)

    if sys.argv[1] == "fenix":
        sync_fenix_strings(fenix_repo, 87, author, debug, dry_run)
