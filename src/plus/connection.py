# -*- coding: utf-8 -*-
#
# connection.py
#
# Copyright (c) 2018, Paul Holleis, Marko Luther
# All rights reserved.
#
#
# ABOUT
# This module connects to the artisan.plus inventory management service

# LICENSE
# This program or module is free software: you can redistribute it and/or
# modify it under the terms of the GNU General Public License as published
# by the Free Software Foundation, either version 2 of the License, or
# version 3 of the License, or (at your option) any later version. It is
# provided for educational purposes and is distributed in the hope that
# it will be useful, but WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See
# the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

try:
    #pylint: disable = E, W, R, C
    from PyQt6.QtCore import QSemaphore # @UnusedImport @Reimport  @UnresolvedImport
except Exception:
    #pylint: disable = E, W, R, C
    from PyQt5.QtCore import QSemaphore # @UnusedImport @Reimport  @UnresolvedImport

from artisanlib import __version__
from typing import Any, Optional, Dict, Final

import datetime
import gzip
import json
import platform
import logging

from plus import config, account, util

_log: Final = logging.getLogger(__name__)


JSON = Any

token_semaphore = QSemaphore(
    1
)  # protects access to the session token which is manipulated only here


def getToken() -> Optional[str]:
    try:
        token_semaphore.acquire(1)
        return config.token
    except Exception as e:  # pylint: disable=broad-except
        _log.exception(e)
        return None
    finally:
        if token_semaphore.available() < 1:
            token_semaphore.release(1)


def getNickname() -> Optional[str]:
    try:
        token_semaphore.acquire(1)
        return config.nickname
    except Exception as e:  # pylint: disable=broad-except
        _log.exception(e)
        return None
    finally:
        if token_semaphore.available() < 1:
            token_semaphore.release(1)


def setToken(token: str, nickname: str = None) -> None:
    try:
        token_semaphore.acquire(1)
        config.token = token
        config.nickname = nickname
        if (
            config.app_window.qmc.operator is None
            or config.app_window.qmc.operator == ""
            and nickname is not None
            and nickname != ""
        ):  # @UndefinedVariable
            config.app_window.qmc.operator = nickname
    finally:
        if token_semaphore.available() < 1:
            token_semaphore.release(1)


def clearCredentials(remove_from_keychain: bool = True) -> None:
    _log.info("clearCredentials()")
    # remove credentials from keychain
    try:
        if (
            config.app_window is not None
            and config.app_window.plus_account is not None
            and remove_from_keychain
        ):  # @UndefinedVariable
            try:
            
                if platform.system().startswith("Windows"):
                    import keyring.backends.Windows  # @UnusedImport
                elif platform.system() == "Darwin":
                    import keyring.backends.macOS  # @UnusedImport @UnresolvedImport
                else:
                    import keyring.backends.SecretService  # @UnusedImport
                import keyring  # @Reimport # imported last to make py2app work
            
                keyring.delete_password(
                    config.app_name, config.app_window.plus_account
                )  # @UndefinedVariable
            except Exception as e:  # pylint: disable=broad-except
                _log.exception(e)
    except Exception: # pylint: disable=broad-except
        # config.app_window might be still unbound
        pass
    try:
        token_semaphore.acquire(1)
        config.token = None
        config.app_window.plus_account = None
        config.passwd = None
        config.nickname = None
        config.account_nr = None
    finally:
        if token_semaphore.available() < 1:
            token_semaphore.release(1)

def setKeyring() -> None:
    try:
        if platform.system().startswith("Windows"):
            import keyring.backends.Windows  # @UnusedImport
        elif platform.system() == "Darwin":
            import keyring.backends.macOS  # @UnusedImport @UnresolvedImport
        else:
            import keyring.backends.SecretService  # @UnusedImport
        import keyring  # @Reimport # imported last to make py2app work
    
        # HACK set keyring backend explicitly
        if platform.system().startswith("Windows"):
            keyring.set_keyring(
                keyring.backends.Windows.WinVaultKeyring()
            )  # @UndefinedVariable
        elif platform.system() == "Darwin":
            try:
                keyring.set_keyring(keyring.backends.macOS.Keyring())
            except Exception:  # pylint: disable=broad-except
                keyring.set_keyring(keyring.backends.OS_X.Keyring())   # type: ignore
        else:  # Linux
            keyring.set_keyring(keyring.backends.SecretService.Keyring())
        # _log.debug("keyring: %s",str(keyring.get_keyring()))
    except Exception as e:  # pylint: disable=broad-except
        _log.exception(e)


# res is assumed to be a dict with non-empty res["result"]["user"]
def extractUserInfo(res, attr: str, default):
    if attr in res and isinstance(res[attr], str) and res[attr] != "":
        return res[attr]
    return default

# takes a JSON result and updates the account limits
def updateLimits(res):
    try:
        if res and config.app_window and "ol" in res:
            ol = res["ol"]
            if "rlimit" in ol and "rused" in ol:
                rlimit = ol["rlimit"]
                used = ol["rused"]
                config.app_window.updatePlusLimitsSignal.emit(rlimit, used)
    except Exception as e:  # pylint: disable=broad-except
        _log.exception(e)

# returns True on successful authentification
def authentify() -> bool:
    _log.info("authentify()")
    import requests # @Reimport
    try:
        if (
            config.app_window is not None
            and config.app_window.plus_account is not None
        ):  # @UndefinedVariable
            # fetch passwd
            if config.passwd is None:
                setKeyring()
                try:
                    if platform.system().startswith("Windows"):
                        import keyring.backends.Windows  # @UnusedImport
                    elif platform.system() == "Darwin":
                        import keyring.backends.macOS  # @UnusedImport @UnresolvedImport
                    else:
                        import keyring.backends.SecretService  # @UnusedImport
                    import keyring  # @Reimport # imported last to make py2app work

                    config.passwd = keyring.get_password(
                        config.app_name, config.app_window.plus_account
                    )  # @UndefinedVariable
                except Exception as e:  # pylint: disable=broad-except
                    _log.exception(e)
            if config.passwd is None:
                _log.debug("-> password not found")
                clearCredentials()
                return False
            _log.debug(
                "-> authentifying %s",
                config.app_window.plus_account,
            )  # @UndefinedVariable
            data = {
                "email": config.app_window.plus_account,
                "password": config.passwd,
            }  # @UndefinedVariable
            r = postData(config.auth_url, data, False)
            _log.debug(
                "-> authentifying reply status code: %s",
                r.status_code,
            )  # @UndefinedVariable
            # returns 404: login wrong and 401: passwd wrong
            res = r.json()
            if (
                "success" in res
                and res["success"]
                and "result" in res
                and "user" in res["result"]
                and "token" in res["result"]["user"]
            ):
                _log.debug(
                    "-> authentified, token received"
                )
                # extract in user/account data
                nickname = extractUserInfo(
                    res["result"]["user"], "nickname", None
                )
                config.app_window.plus_language = extractUserInfo(
                    res["result"]["user"], "language", "en"
                )
                config.app_window.plus_paidUntil = None
                config.app_window.plus_subscription = None
                if "account" in res["result"]["user"]:
                    config.app_window.plus_subscription = extractUserInfo(
                        res["result"]["user"]["account"],
                        "subscription",
                        None,
                    )
                    paidUntil = extractUserInfo(
                        res["result"]["user"]["account"], "paidUntil", None
                    )
                    try:
                        if paidUntil is not None:
                            config.app_window.plus_paidUntil = (
                                util.ISO86012datetime(paidUntil)
                            )
                    except Exception as e:  # pylint: disable=broad-except
                        _log.exception(e)
                    
                    if "limit" in res["result"]["user"]["account"]:
                        ol = res["result"]["user"]["account"]["limit"]
                        if "rlimit" in ol and "rused" in ol:
                            rlimit = ol["rlimit"]
                            used = ol["rused"]
                            config.app_window.updatePlusLimitsSignal.emit(rlimit, used)
                        
                if config.app_window.plus_paidUntil is not None and (
                    config.app_window.plus_paidUntil.date()
                    - datetime.datetime.now().date()
                ).days < (-config.expired_subscription_max_days):
                    _log.debug(
                        (
                            "-> authentication failed due to"
                            " long expired subscription"
                        )
                    )
                    if "error" in res:
                        config.app_window.sendmessage(
                            res["error"]
                        )  # @UndefinedVariable
                    clearCredentials()
                    return False
                if "readonly" in res["result"]["user"] and isinstance(
                    res["result"]["user"]["readonly"], bool
                ):
                    config.app_window.plus_readonly = res["result"]["user"][
                        "readonly"
                    ]
                else:
                    config.app_window.plus_readonly = False
                #
                setToken(res["result"]["user"]["token"], nickname)
                if (
                    "account" in res["result"]["user"]
                    and "_id" in res["result"]["user"]["account"]
                ):
                    account_nr = account.setAccount(
                        res["result"]["user"]["account"]["_id"]
                    )
                    config.account_nr = account_nr
                    _log.debug(
                        "-> account: %s", account_nr
                    )
                return True
            _log.debug("-> authentication failed")
            if "error" in res:
                config.app_window.sendmessage(
                    res["error"]
                )  # @UndefinedVariable
            clearCredentials()
            return False
        return False
    except requests.exceptions.RequestException as e:
        _log.exception(e)
        raise (e)
    except Exception as e:
        _log.exception(e)
        clearCredentials()
        raise (e)


def getHeaders(
    authorized: bool = True, decompress: bool = True) -> Dict[str, str]:
    os, os_version = config.app_window.get_os()  # @UndefinedVariable
    headers = {
        "user-agent": f"Artisan/{__version__} ({os}; {os_version})"
    }
    try:
        locale = config.app_window.locale_str
        if locale is not None and locale != "":
            assert isinstance(locale, str)
            locale = locale.lower().replace("_", "-")
            headers["Accept-Language"] = locale
    except Exception as e:  # pylint: disable=broad-except
        _log.exception(e)
    if authorized:
        token = getToken()
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
    if decompress:
        headers[
            "Accept-Encoding"
        ] = "deflate, compress, gzip"  # identity should not be in here!
    return headers


def sendData(url: str, data: Dict[Any, Any], verb: str) -> Any:
    if verb == "POST":
        return postData(url, data)
    return putData(url, data)


# TODO: implement! # pylint: disable=fixme
def putData(url: str, data: Dict[Any, Any]) -> Any:
    del url, data


def getHeadersAndData(authorized: bool, compress: bool, jsondata: JSON):
    headers = getHeaders(authorized, decompress=compress)
    headers["Content-Type"] = "application/json"
    if compress and len(jsondata) > config.post_compression_threshold:
        postdata = gzip.compress(jsondata)
        _log.debug("-> compressed size %s", len(postdata))
        headers["Content-Encoding"] = "gzip"
    else:
        postdata = jsondata
    return headers, postdata


def postData(
    url: str,
    data,
    authorized: bool = True,
    compress: bool = config.compress_posts,
) -> Any:
    # don't log POST data as it might contain credentials!
    _log.info("postData(%s,_data_,%s)", url, authorized)
    jsondata = json.dumps(data).encode("utf8")
    _log.debug("-> size %s", len(jsondata))
    headers, postdata = getHeadersAndData(authorized, compress, jsondata)
    import requests  # @Reimport
    r = requests.post(
        url,
        headers=headers,
        data=postdata,
        verify=config.verify_ssl,
        timeout=(config.connect_timeout, config.read_timeout),
    )
    _log.debug("-> status %s, time %s", r.status_code, r.elapsed.total_seconds())
    if authorized and r.status_code == 401:  # authorisation failed
        _log.debug("-> session token outdated (401)")
        # we re-authentify by renewing the session token and try again
        if authentify():
            headers, postdata = getHeadersAndData(
                authorized, compress, jsondata
            )  # recreate header with new token
            r = requests.post(
                url,
                headers=headers,
                data=postdata,
                verify=config.verify_ssl,
                timeout=(config.connect_timeout, config.read_timeout),
            )
            _log.debug("-> status %s, time %s", r.status_code, r.elapsed.total_seconds())
    return r


def getData(url: str, authorized: bool = True) -> Any:
    _log.info("getData(%s,%s)", url, authorized)
    headers = getHeaders(authorized)
    #    _log.debug("-> request headers %s",headers)
    import requests  # @Reimport
    r = requests.get(
        url,
        headers=headers,
        verify=config.verify_ssl,
        timeout=(config.connect_timeout, config.read_timeout),
    )
    _log.debug("-> status %s", r.status_code)
    #    _log.debug("-> headers %s",r.headers)
    _log.debug("-> time %s", r.elapsed.total_seconds())
    if authorized and r.status_code == 401:  # authorisation failed
        _log.debug(
            "-> session token outdated (404) - re-authentify"
        )
        # we re-authentify by renewing the session token and try again
        authentify()
        headers = getHeaders(authorized)  # recreate header with new token
        r = requests.get(
            url,
            headers=headers,
            verify=config.verify_ssl,
            timeout=(config.connect_timeout, config.read_timeout),
        )
        _log.debug("-> status %s", r.status_code)
        #        _log.debug("-> headers %s",r.headers)
        _log.debug(
            "-> time %s", r.elapsed.total_seconds()
        )
    try:
        _log.debug("-> size %s", len(r.content))
    #        _log.debug("-> data %s",r.json())
    except Exception:  # pylint: disable=broad-except
        pass
    return r
