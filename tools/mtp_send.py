# Sends a file into a folder on an MTP device (Garmin watches reject mtp-sendfile
# because libmtp cannot resolve their storage id from a path). Needs libmtp and
# no gvfs process holding the device.
import ctypes, ctypes.util, os, sys
lib = ctypes.CDLL(ctypes.util.find_library("mtp") or "libmtp.so.9")

class Folder(ctypes.Structure):
    pass
Folder._fields_ = [("folder_id", ctypes.c_uint32), ("parent_id", ctypes.c_uint32),
                   ("storage_id", ctypes.c_uint32), ("name", ctypes.c_char_p),
                   ("sibling", ctypes.POINTER(Folder)), ("child", ctypes.POINTER(Folder))]

class File(ctypes.Structure):
    pass
File._fields_ = [("item_id", ctypes.c_uint32), ("parent_id", ctypes.c_uint32),
                 ("storage_id", ctypes.c_uint32), ("filename", ctypes.c_char_p),
                 ("filesize", ctypes.c_uint64), ("modificationdate", ctypes.c_long),
                 ("filetype", ctypes.c_int), ("next", ctypes.POINTER(File))]

lib.LIBMTP_Get_First_Device.restype = ctypes.c_void_p
lib.LIBMTP_Get_Folder_List.restype = ctypes.POINTER(Folder)
lib.LIBMTP_Get_Folder_List.argtypes = [ctypes.c_void_p]
lib.LIBMTP_Send_File_From_File.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.POINTER(File), ctypes.c_void_p, ctypes.c_void_p]
lib.LIBMTP_Dump_Errorstack.argtypes = [ctypes.c_void_p]
lib.LIBMTP_Release_Device.argtypes = [ctypes.c_void_p]

def find(node, path):
    while node:
        f = node.contents
        if f.name.decode() == path[0]:
            return f if len(path) == 1 else find(f.child, path[1:])
        node = f.sibling
    return None

local, remote_dir = sys.argv[1], sys.argv[2].split("/")
lib.LIBMTP_Init()
dev = lib.LIBMTP_Get_First_Device()
if not dev:
    sys.exit("no device")
try:
    folder = find(lib.LIBMTP_Get_Folder_List(dev), remote_dir)
    if folder is None:
        sys.exit("folder not found")
    print("target folder", folder.folder_id, "storage", hex(folder.storage_id))
    f = File(0, folder.folder_id, folder.storage_id, os.path.basename(local).encode(),
             os.path.getsize(local), 0, 44, None)
    rc = lib.LIBMTP_Send_File_From_File(dev, local.encode(), ctypes.byref(f), None, None)
    if rc != 0:
        lib.LIBMTP_Dump_Errorstack(dev)
        sys.exit("send failed")
    print("sent, item id", f.item_id)
finally:
    lib.LIBMTP_Release_Device(dev)
