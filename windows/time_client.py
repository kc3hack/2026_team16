import asyncio
import websockets
import json
import argparse
import logging
import sys
import ctypes
import win32security

from windows_utils import enable_privilege, set_timezone_offset

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Constants
USER_ID = 1
SERVER_URL = f"ws://127.0.0.1:8000/ws/{USER_ID}"

async def connect_to_server(dry_run=False):
    logger.info(f"Connecting to: {SERVER_URL}")
    if dry_run:
        logger.info("⚠️ RUNNING IN DRY-RUN MODE.")

    while True:
        try:
            async with websockets.connect(SERVER_URL) as websocket:
                logger.info("✅ Connected to server!")
                
                while True:
                    message = await websocket.recv()
                    logger.debug(f"Received: {message}")
                    
                    try:
                        data = json.loads(message)
                        if data.get("type") == "OFFSET_UPDATE":
                            offset = data.get("offset_minutes", 0)
                            reason = data.get("reason", "Unknown")
                            
                            logger.info(f"⚡ Directive: Offset {offset} min (Reason: {reason})")
                            
                            set_timezone_offset(offset, dry_run=dry_run)
                            
                    except json.JSONDecodeError:
                        logger.error("Failed to decode JSON")
                    except Exception as e:
                        logger.error(f"Error processing message: {e}")

        except websockets.exceptions.ConnectionClosed:
            logger.warning("⚠️ Connection closed. Reconnecting in 5 seconds...")
            await asyncio.sleep(5)
        except ConnectionRefusedError:
            logger.warning("⚠️ Connection refused. Is the server running? Retrying in 5 seconds...")
            await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Time Distortion Client (Timezone Hack)")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without changing system settings")
    args = parser.parse_args()

    if not args.dry_run:
        try:
            is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
            if not is_admin:
                logger.warning("⚠️ Running without Administrator privileges. Timezone changes will fail.")
            else:
                # Enable Privilege using utils
                if not enable_privilege(win32security.SE_TIME_ZONE_NAME):
                     logger.warning("⚠️ Failed to enable SeTimeZonePrivilege.")
        except Exception as e:
            logger.error(f"Startup check failed: {e}")

    try:
        if sys.platform == 'win32':
             asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(connect_to_server(dry_run=args.dry_run))
    except KeyboardInterrupt:
        logger.info("Client stopped by user. Resetting timezone...")
        if not args.dry_run:
            set_timezone_offset(0)
