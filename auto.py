#!/usr/bin/env python
from __future__ import print_function

import sys
from typing import Match, cast

from common import _L, DEBUG, DIRNAME, INFO
# from query import BL3
from query import Key, known_games, known_platforms
from shift import ShiftClient, Status

client: ShiftClient = None # type: ignore

LICENSE_TEXT = """\
========================================================================
autoshift  Copyright (C) 2019  Fabian Schweinfurth
This program comes with ABSOLUTELY NO WARRANTY; for details see LICENSE.
This is free software, and you are welcome to redistribute it
under certain conditions; see LICENSE for details.
========================================================================
"""


def redeem(key: Key):
    import query
    """Redeem key and set as redeemed if successfull"""

    _L.info(f"Trying to redeem {key.reward} ({key.code}) on platform {key.platform}")
    status = client.redeem(key.code, known_games[key.game], key.platform)
    _L.debug(f"Status: {status}")

    # set redeemed status
    if status in (Status.SUCCESS, Status.REDEEMED,
                  Status.EXPIRED, Status.INVALID):
        query.db.set_redeemed(key)

    # notify user
    try:
        # this may fail if there are other `{<something>}` in the string..
        _L.info("  " + status.msg.format(**locals()))
    except:
        _L.info("  " + status.msg)

    # Send notification on success
    if status == Status.SUCCESS:
        import os
        apprise_url = os.environ.get("APPRISE_URL")
        if apprise_url:
            try:
                from apprise import Apprise
                a = Apprise()
                a.add(apprise_url)
                a.notify(
                    body=f"Redeemed {key.reward} ({key.code}) on {key.platform}",
                    title=f"SHiFT Key Redeemed: {key.reward}"
                )
            except Exception as e:
                _L.warn(f"Failed to send Apprise notification: {e}")
    return status == Status.SUCCESS


def query_keys(games: list[str], platforms: list[str]):
    """Query new keys for given games and platforms

    Returns dict of dicts of lists with [game][platform] as keys"""
    from itertools import groupby

    import query
    all_keys: dict[str, dict[str, list[Key]]] = {}

    keys = list(query.db.get_keys(None, None))
    # parse all keys
    query.update_keys()
    new_keys = list(query.db.get_keys(None, None))

    diff = len(new_keys) - len(keys)
    _L.info(f"done. ({diff if diff else 'no'} new Keys)")

    _g = lambda key: key.game
    _p = lambda key: key.platform
    # Use all known platforms except 'universal' by default
    all_platforms = [p for p in known_platforms if p != "universal"]

    for g, g_keys in groupby(sorted(new_keys, key=_g), _g):
        if g not in games:
            continue
        all_keys[g] = {p: [] for p in all_platforms}
        for platform, p_keys in groupby(sorted(g_keys, key=_p), _p):
            # Always distribute keys to all platforms (except 'universal')
            if platform == "universal":
                for p in all_platforms:
                    all_keys[g][p].extend(key.copy().set(platform=p) for key in p_keys)
            elif platform in all_platforms:
                all_keys[g][platform].extend(p_keys)

        for p in all_platforms:
            # count the new keys
            n_golden = sum(int(cast(Match[str], m).group(1) or 1)
                            for m in
                            filter(lambda m:
                                    m  and m.group(1) is not None,
                                    map(lambda key: query.r_golden_keys.match(key.reward),
                                        all_keys[g][p])))

            _L.info(f"You have {n_golden} golden {g.upper()} keys to redeem for {p.upper()}")

    return all_keys


def setup_argparser():
    import argparse
    import textwrap
    games = list(known_games.keys())
    platforms = list(known_platforms.without("universal").keys())

    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("-u", "--user",
                        default=None,
                        help=("User login you want to use "
                              "(optional. You will be prompted to enter your "
                              " credentials if you didn't specify them here)"))
    parser.add_argument("-p", "--pass",
                        help=("Password for your login. "
                              "(optional. You will be prompted to enter your "
                              " credentials if you didn't specify them here)"))
    parser.add_argument("--golden",
                        action="store_true",
                        help="Only redeem golden keys")
    parser.add_argument("--non-golden", dest="non_golden",
                        action="store_true",
                        help="Only redeem non-golden keys")
    parser.add_argument("--games",
                        type=str, required=False,
                        choices=games, nargs="+",
                        help=("Games you want to query SHiFT keys for. If omitted, all games will be used."))
    parser.add_argument("--platforms",
                        type=str, required=False,
                        choices=platforms, nargs="+",
                        help=("Platforms you want to query SHiFT keys for. If omitted, all platforms will be used."))
    parser.add_argument("--limit",
                        type=int, default=200,
                        help=textwrap.dedent("""\
                        Max number of golden Keys you want to redeem.
                        (default 200)
                        NOTE: You can only have 255 keys at any given time!""")) # noqa
    parser.add_argument("--schedule",
                        type=float, const=2, nargs="?",
                        help="Keep checking for keys and redeeming every hour")
    parser.add_argument("-v", dest="verbose",
                        action="store_true",
                        help="Verbose mode")

    return parser


def main(args):
    global client
    from time import sleep

    import query
    from query import db, r_golden_keys

    import os
    apprise_url = os.environ.get("APPRISE_URL")
    summary = {
        "redeemed": 0,
        "failed": 0,
        "games": set(),
        "platforms": set(),
        "errors": []
    }
    try:
        with db:
            if not client:
                client = ShiftClient(args.user, args.pw)

            # Use all games/platforms if not specified
            games = args.games if args.games else list(known_games.keys())
            plats = args.platforms if args.platforms else [p for p in known_platforms if p != "universal"]

            all_keys = query_keys(games, plats)

            # redeem 0 golden keys but only golden??... duh
            if not args.limit and args.golden:
                _L.info("Not redeeming anything ...")
                return

            _L.info("Trying to redeem now.")

            # always try all codes for all games/platforms unless user specified
            for code in set(key.code for g in all_keys for p in all_keys[g] for key in all_keys[g][p]):
                for game in games:
                    for platform in plats:
                        # find key for this code/game/platform
                        key = None
                        for g in all_keys:
                            for p in all_keys[g]:
                                for k in all_keys[g][p]:
                                    if k.code == code and k.game == game and k.platform == platform:
                                        key = k
                                        break
                                if key:
                                    break
                            if key:
                                break
                        if not key:
                            # create a new Key object for this permutation
                            key = Key(code=code, game=game, platform=platform, reward="Reddit code")
                        if key.redeemed:
                            continue
                        num_g_keys = 0
                        m = r_golden_keys.match(key.reward)
                        # skip keys we don't want
                        if ((args.golden and not m) or (args.non_golden and m)):
                            continue
                        if m:
                            num_g_keys = int(m.group(1) or 1)
                            if args.limit <= 0:
                                continue
                            if (args.limit - num_g_keys) < 0:
                                continue
                        sleep_time = 60
                        max_sleep = 300
                        while True:
                            try:
                                redeemed = redeem(key)
                            except Exception as e:
                                summary["failed"] += 1
                                summary["errors"].append(f"{key.code} ({key.platform}): {e}")
                                break
                            if client.last_status == Status.SLOWDOWN:
                                _L.info(f"Too many requests. Sleeping for {sleep_time} seconds and retrying...")
                                sleep(sleep_time)
                                sleep_time = min(sleep_time * 2, max_sleep)
                                continue
                            if redeemed:
                                args.limit -= num_g_keys
                                summary["redeemed"] += 1
                                summary["games"].add(game)
                                summary["platforms"].add(platform)
                                _L.info(f"Redeeming another {args.limit} Keys")
                            else:
                                summary["failed"] += 1
                                if client.last_status == Status.TRYLATER:
                                    if apprise_url:
                                        try:
                                            from apprise import Apprise
                                            a = Apprise()
                                            a.add(apprise_url)
                                            a.notify(
                                                body="Redemption stopped: SHiFT hourly limit reached.",
                                                title="SHiFT Redemption: Try Later"
                                            )
                                        except Exception as e:
                                            _L.warn(f"Failed to send Apprise notification: {e}")
                                    break
                            break
            _L.info("No more keys left!")
    except Exception as e:
        summary["errors"].append(str(e))
        summary["failed"] += 1
        _L.warn(f"Redemption process failed: {e}")
    finally:
        if apprise_url:
            try:
                from apprise import Apprise
                a = Apprise()
                a.add(apprise_url)
                body = (
                    f"Redeemed: {summary['redeemed']}\n"
                    f"Failed: {summary['failed']}\n"
                    f"Games: {', '.join(summary['games']) if summary['games'] else 'None'}\n"
                    f"Platforms: {', '.join(summary['platforms']) if summary['platforms'] else 'None'}\n"
                )
                if summary["errors"]:
                    body += "Errors:\n" + "\n".join(summary["errors"])
                a.notify(
                    body=body,
                    title="SHiFT Redemption Summary"
                )
            except Exception as e:
                _L.warn(f"Failed to send Apprise notification: {e}")


if __name__ == "__main__":
    import os

    # only print license text on first use
    if not os.path.exists(os.path.join(DIRNAME, "data", ".cookies.save")):
        print(LICENSE_TEXT)


    # build argument parser
    parser = setup_argparser()
    args = parser.parse_args()


    # Support reading all parameters from environment variables if not provided
    import os
    if not args.user:
        args.user = os.environ.get("SHIFT_USER")
    args.pw = getattr(args, "pass") or os.environ.get("SHIFT_PASS")
    if not args.games:
        env_games = os.environ.get("SHIFT_GAMES")
        if env_games:
            args.games = env_games.split()
    if not args.platforms:
        env_platforms = os.environ.get("SHIFT_PLATFORMS")
        if env_platforms:
            args.platforms = env_platforms.split()
    if not args.golden:
        args.golden = bool(os.environ.get("SHIFT_GOLDEN"))
    if not args.non_golden:
        args.non_golden = bool(os.environ.get("SHIFT_NON_GOLDEN"))
    if args.limit == 200:  # only override if default
        env_limit = os.environ.get("SHIFT_LIMIT")
        if env_limit:
            try:
                args.limit = int(env_limit)
            except ValueError:
                pass
    if not args.schedule:
        env_schedule = os.environ.get("SHIFT_SCHEDULE")
        if env_schedule:
            try:
                args.schedule = float(env_schedule)
            except ValueError:
                pass
    if not args.verbose:
        args.verbose = bool(os.environ.get("SHIFT_VERBOSE"))

    _L.setLevel(INFO)
    if args.verbose:
        _L.setLevel(DEBUG)
        _L.debug("Debug mode on")

    if args.schedule and args.schedule < 2:
        _L.warn(f"Running this tool every {args.schedule} hours would result in "
                "too many requests.\n"
                "Scheduling changed to run every 2 hours!")

    # always execute at least once
    main(args)

    # scheduling will start after first trigger (so in an hour..)
    if args.schedule:
        hours = int(args.schedule)
        minutes = int((args.schedule-hours)*60+1e-5)
        _L.info(f"Scheduling to run every {hours:02}:{minutes:02} hours")
        from apscheduler.schedulers.blocking import BlockingScheduler
        scheduler = BlockingScheduler()
        # fire every 1h5m (to prevent being blocked by the shift platform.)
        #  (5min safe margin because it somtimes fires a few seconds too early)
        scheduler.add_job(main, "interval", args=(args,), hours=args.schedule)
        print(f"Press Ctrl+{'Break' if os.name == 'nt' else 'C'} to exit")

        try:
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            pass
    _L.info("Goodbye.")
