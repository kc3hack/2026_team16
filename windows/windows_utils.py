import ctypes
from ctypes import wintypes
import win32api
import win32security
import win32con
import logging

logger = logging.getLogger(__name__)

# --- CTypes Definitions for Timezone ---
class SYSTEMTIME(ctypes.Structure):
    _fields_ = [
        ("wYear", wintypes.WORD),
        ("wMonth", wintypes.WORD),
        ("wDayOfWeek", wintypes.WORD),
        ("wDay", wintypes.WORD),
        ("wHour", wintypes.WORD),
        ("wMinute", wintypes.WORD),
        ("wSecond", wintypes.WORD),
        ("wMilliseconds", wintypes.WORD),
    ]

class DYNAMIC_TIME_ZONE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("Bias", ctypes.c_long),
        ("StandardName", ctypes.c_wchar * 32),
        ("StandardDate", SYSTEMTIME),
        ("StandardBias", ctypes.c_long),
        ("DaylightName", ctypes.c_wchar * 32),
        ("DaylightDate", SYSTEMTIME),
        ("DaylightBias", ctypes.c_long),
        ("TimeZoneKeyName", ctypes.c_wchar * 128),
        ("DynamicDaylightTimeDisabled", ctypes.c_bool),
    ]

kernel32 = ctypes.windll.kernel32

def enable_privilege(privilege_name):
    """Enables the specified privilege for the current process token using pywin32."""
    try:
        flags = win32security.TOKEN_ADJUST_PRIVILEGES | win32security.TOKEN_QUERY
        hToken = win32security.OpenProcessToken(win32api.GetCurrentProcess(), flags)
        luid = win32security.LookupPrivilegeValue(None, privilege_name)
        new_privileges = [(luid, win32security.SE_PRIVILEGE_ENABLED)]
        try:
            win32security.AdjustTokenPrivileges(hToken, 0, new_privileges)
        except Exception as e:
            logger.error(f"AdjustTokenPrivileges failed: {e}")
            return False
            
        if win32api.GetLastError() == 1300: # ERROR_NOT_ALL_ASSIGNED
            logger.error(f"Privilege {privilege_name} not held by the user token (Not Admin?).")
            return False
            
        logger.info(f"✅ Privilege enabled: {privilege_name}")
        return True
    except Exception as e:
        logger.error(f"Failed to enable privilege {privilege_name}: {e}")
        return False

def set_timezone_offset(offset_minutes, dry_run=False):
    """
    Changes the system timezone bias using SetDynamicTimeZoneInformation (via ctypes).
    Assuming JST standard (-540) as base.
    """
    if dry_run:
        logger.info(f"[DRY-RUN] Will shift Timezone by {offset_minutes} minutes.")
        return

    BASE_BIAS = -540 # JST (UTC+9)
    new_bias = BASE_BIAS - offset_minutes
    
    logger.info(f"Target Offset: {offset_minutes} min. Setting Bias to {new_bias} (Base: {BASE_BIAS})")

    # Create Structure
    dtzi = DYNAMIC_TIME_ZONE_INFORMATION()
    dtzi.Bias = new_bias
    dtzi.StandardName = "Engineer Time (Standard)"
    dtzi.DaylightName = "Engineer Time (Daylight)"
    dtzi.TimeZoneKeyName = "EngineerTime"
    dtzi.DynamicDaylightTimeDisabled = True
    
    dtzi.StandardBias = 0
    dtzi.DaylightBias = 0
    dtzi.StandardDate.wMonth = 0
    dtzi.DaylightDate.wMonth = 0

    try:
        success = kernel32.SetDynamicTimeZoneInformation(ctypes.byref(dtzi))
        if success:
             logger.info(f"✅ Timezone changed! Virtual Offset: {offset_minutes} mins.")
             win32api.SendMessage(win32con.HWND_BROADCAST, win32con.WM_SETTINGCHANGE, 0, "intl")
        else:
             err = ctypes.GetLastError()
             logger.error(f"❌ Failed to set timezone. Error Code: {err}")
             
    except Exception as e:
        logger.error(f"❌ Exception setting timezone: {e}")
