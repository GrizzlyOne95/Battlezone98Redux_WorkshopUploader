import ctypes
import os
import time


class SteamParamStringArray(ctypes.Structure):
    _fields_ = [
        ("strings", ctypes.POINTER(ctypes.c_char_p)),
        ("num_strings", ctypes.c_int),
    ]


class SubmitItemUpdateResult(ctypes.Structure):
    _fields_ = [
        ("result", ctypes.c_int),
        ("needs_legal_agreement", ctypes.c_bool),
        ("_padding", ctypes.c_ubyte * 3),
        ("published_file_id", ctypes.c_uint64),
    ]


class SteamworksTagUpdater:
    ERESULT_OK = 1
    SUBMIT_ITEM_UPDATE_CALLBACK_ID = 3404
    STEAM_CLIENT_VERSION = b"SteamClient017"
    STEAM_UTILS_VERSION = b"SteamUtils008"
    STEAM_UGC_VERSIONS = [f"STEAMUGC_INTERFACE_VERSION{i:03d}".encode("ascii") for i in range(30, 0, -1)]

    def __init__(self, logger=None):
        self.logger = logger

    def log(self, msg):
        if self.logger:
            self.logger(msg)

    def _ensure_appid_file(self, base_dir, appid):
        if not base_dir:
            return None
        path = os.path.join(base_dir, "steam_appid.txt")
        if os.path.exists(path):
            return None
        with open(path, "w", encoding="ascii") as f:
            f.write(str(appid).strip() + "\n")
        return path

    def find_steam_api_path(self, base_dir=None):
        candidates = []
        if base_dir:
            candidates.append(os.path.join(base_dir, "steam_api.dll"))

        for env_var in ("BZR_GAME_DIR",):
            value = os.environ.get(env_var, "").strip()
            if value:
                candidates.append(os.path.join(value, "steam_api.dll"))

        user_profile = os.environ.get("USERPROFILE", "")
        if user_profile:
            candidates.append(os.path.join(user_profile, "Documents", "Battlezone 98 Redux", "steam_api.dll"))

        program_files_x86 = os.environ.get("PROGRAMFILES(X86)", "")
        if program_files_x86:
            candidates.append(os.path.join(program_files_x86, "Steam", "steamapps", "common", "Battlezone 98 Redux", "steam_api.dll"))

        candidates.append(os.path.join("C:\\steamcmd", "steamapps", "content", "app_450970", "depot_450971", "steam_api.dll"))

        seen = set()
        for path in candidates:
            norm = os.path.normpath(path)
            if norm in seen:
                continue
            seen.add(norm)
            if os.path.exists(norm):
                return norm
        return None

    def _configure_exports(self, dll):
        dll.SteamAPI_Init.restype = ctypes.c_bool
        dll.SteamAPI_Shutdown.restype = None
        dll.SteamAPI_RunCallbacks.restype = None
        dll.SteamAPI_GetHSteamUser.restype = ctypes.c_int
        dll.SteamAPI_GetHSteamPipe.restype = ctypes.c_int
        dll.SteamClient.restype = ctypes.c_void_p

        dll.SteamAPI_ISteamClient_GetISteamUGC.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_char_p,
        ]
        dll.SteamAPI_ISteamClient_GetISteamUGC.restype = ctypes.c_void_p

        dll.SteamAPI_ISteamClient_GetISteamUtils.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_char_p,
        ]
        dll.SteamAPI_ISteamClient_GetISteamUtils.restype = ctypes.c_void_p

        dll.SteamAPI_ISteamUGC_StartItemUpdate.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint64,
        ]
        dll.SteamAPI_ISteamUGC_StartItemUpdate.restype = ctypes.c_uint64

        dll.SteamAPI_ISteamUGC_SetItemTags.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint64,
            ctypes.POINTER(SteamParamStringArray),
        ]
        dll.SteamAPI_ISteamUGC_SetItemTags.restype = ctypes.c_bool

        dll.SteamAPI_ISteamUGC_SubmitItemUpdate.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint64,
            ctypes.c_char_p,
        ]
        dll.SteamAPI_ISteamUGC_SubmitItemUpdate.restype = ctypes.c_uint64

        dll.SteamAPI_ISteamUtils_IsAPICallCompleted.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint64,
            ctypes.POINTER(ctypes.c_bool),
        ]
        dll.SteamAPI_ISteamUtils_IsAPICallCompleted.restype = ctypes.c_bool

        dll.SteamAPI_ISteamUtils_GetAPICallResult.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint64,
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_bool),
        ]
        dll.SteamAPI_ISteamUtils_GetAPICallResult.restype = ctypes.c_bool

    def _load_dll(self, dll_path):
        dll_dir = os.path.dirname(dll_path)
        add_dir = getattr(os, "add_dll_directory", None)
        if add_dir:
            dll_cookie = add_dir(dll_dir)
        else:
            dll_cookie = None
        try:
            dll = ctypes.WinDLL(dll_path)
        finally:
            if dll_cookie is not None:
                dll_cookie.close()
        self._configure_exports(dll)
        return dll

    def _get_ugc_interface(self, dll, client, h_user, h_pipe):
        for version in self.STEAM_UGC_VERSIONS:
            ugc = dll.SteamAPI_ISteamClient_GetISteamUGC(client, h_user, h_pipe, version)
            if ugc:
                return ugc, version.decode("ascii")
        return None, None

    def _wait_for_submit_result(self, dll, steam_utils, api_call, timeout_seconds):
        deadline = time.time() + timeout_seconds
        call_failed = ctypes.c_bool(False)

        while time.time() < deadline:
            dll.SteamAPI_RunCallbacks()
            is_complete = dll.SteamAPI_ISteamUtils_IsAPICallCompleted(steam_utils, api_call, ctypes.byref(call_failed))
            if is_complete:
                if call_failed.value:
                    raise RuntimeError("Steamworks submit call failed before returning a result.")

                result = SubmitItemUpdateResult()
                io_failure = ctypes.c_bool(False)
                ok = dll.SteamAPI_ISteamUtils_GetAPICallResult(
                    steam_utils,
                    api_call,
                    ctypes.byref(result),
                    ctypes.sizeof(result),
                    self.SUBMIT_ITEM_UPDATE_CALLBACK_ID,
                    ctypes.byref(io_failure),
                )
                if not ok:
                    raise RuntimeError("Steamworks submit completed but no SubmitItemUpdateResult was returned.")
                if io_failure.value:
                    raise RuntimeError("Steamworks submit completed with I/O failure.")
                if result.result != self.ERESULT_OK:
                    raise RuntimeError(f"Steamworks submit returned EResult {result.result}.")
                return {
                    "publishedfileid": str(result.published_file_id),
                    "needs_legal_agreement": bool(result.needs_legal_agreement),
                }
            time.sleep(0.1)

        raise TimeoutError("Timed out waiting for Steamworks tag update to complete.")

    def try_update_tags(
        self,
        appid,
        publishedfileid,
        tags,
        change_note="",
        dll_path=None,
        base_dir=None,
        timeout_seconds=20.0,
        create_appid_file=False,
    ):
        if os.name != "nt":
            raise RuntimeError("Steamworks tag update is only supported on Windows.")

        clean_tags = [tag.strip() for tag in tags if str(tag).strip()]
        if not clean_tags:
            raise ValueError("No tags were provided.")

        target_dll = dll_path or self.find_steam_api_path(base_dir=base_dir)
        if not target_dll:
            raise FileNotFoundError("steam_api.dll was not found in known Battlezone locations.")

        created_appid_path = None
        if create_appid_file:
            created_appid_path = self._ensure_appid_file(base_dir, appid)
            if created_appid_path:
                self.log(f"Created temporary steam_appid.txt for native Steamworks tags: {created_appid_path}")

        self.log(f"Attempting Steamworks tag update via {target_dll}")
        dll = self._load_dll(target_dll)
        try:
            if not dll.SteamAPI_Init():
                raise RuntimeError("SteamAPI_Init failed. Make sure Steam is running and the game AppID is available.")

            h_user = dll.SteamAPI_GetHSteamUser()
            h_pipe = dll.SteamAPI_GetHSteamPipe()
            client = dll.SteamClient()
            if not client or not h_user or not h_pipe:
                raise RuntimeError("Steamworks client handles were not available after SteamAPI_Init.")

            ugc, ugc_version = self._get_ugc_interface(dll, client, h_user, h_pipe)
            if not ugc:
                raise RuntimeError("Failed to acquire ISteamUGC interface.")

            steam_utils = dll.SteamAPI_ISteamClient_GetISteamUtils(client, h_pipe, self.STEAM_UTILS_VERSION)
            if not steam_utils:
                raise RuntimeError("Failed to acquire ISteamUtils interface.")

            update_handle = dll.SteamAPI_ISteamUGC_StartItemUpdate(ugc, int(appid), int(publishedfileid))
            if not update_handle:
                raise RuntimeError("Steamworks StartItemUpdate returned an invalid handle.")

            encoded_tags = [tag.encode("utf-8") for tag in clean_tags]
            tag_array = (ctypes.c_char_p * len(encoded_tags))(*encoded_tags)
            steam_tags = SteamParamStringArray(strings=tag_array, num_strings=len(encoded_tags))

            if not dll.SteamAPI_ISteamUGC_SetItemTags(ugc, update_handle, ctypes.byref(steam_tags)):
                raise RuntimeError("Steamworks SetItemTags returned failure.")

            submit_call = dll.SteamAPI_ISteamUGC_SubmitItemUpdate(
                ugc,
                update_handle,
                (change_note or "").encode("utf-8"),
            )
            if not submit_call:
                raise RuntimeError("Steamworks SubmitItemUpdate returned an invalid API call handle.")

            result = self._wait_for_submit_result(dll, steam_utils, submit_call, timeout_seconds=timeout_seconds)
            result["method"] = "steamworks"
            result["ugc_version"] = ugc_version
            result["dll_path"] = target_dll
            return result
        finally:
            try:
                dll.SteamAPI_Shutdown()
            except Exception:
                pass
            if created_appid_path and os.path.exists(created_appid_path):
                try:
                    os.remove(created_appid_path)
                    self.log("Removed temporary steam_appid.txt after native Steamworks tag attempt.")
                except Exception:
                    pass
