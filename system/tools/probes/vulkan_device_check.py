"""Does Vulkan see any device at all on this host? A minimal ctypes probe, because vulkaninfo is not installed.

If `vkCreateInstance`/`vkEnumeratePhysicalDevices` returns devices, the ICD is fine and Citron's failure is about how *it* initialises; if it
returns none or errors, the host's Vulkan stack is the problem and no emulator configuration will help.
"""
import ctypes
import ctypes.util

VK_SUCCESS = 0
VK_STRUCTURE_TYPE_APPLICATION_INFO = 0


class VkApplicationInfo(ctypes.Structure):
    _fields_ = [("sType", ctypes.c_int), ("pNext", ctypes.c_void_p),
                ("pApplicationName", ctypes.c_char_p), ("applicationVersion", ctypes.c_uint32),
                ("pEngineName", ctypes.c_char_p), ("engineVersion", ctypes.c_uint32),
                ("apiVersion", ctypes.c_uint32)]


class VkInstanceCreateInfo(ctypes.Structure):
    _fields_ = [("sType", ctypes.c_int), ("pNext", ctypes.c_void_p), ("flags", ctypes.c_uint32),
                ("pApplicationInfo", ctypes.POINTER(VkApplicationInfo)),
                ("enabledLayerCount", ctypes.c_uint32), ("ppEnabledLayerNames", ctypes.c_void_p),
                ("enabledExtensionCount", ctypes.c_uint32), ("ppEnabledExtensionNames", ctypes.c_void_p)]


def main() -> int:
    name = ctypes.util.find_library("vulkan") or "libvulkan.so.1"
    print("loader:", name)
    try:
        vk = ctypes.CDLL(name)
    except OSError as exc:
        print("cannot load the loader:", exc)
        return 1

    app = VkApplicationInfo(sType=VK_STRUCTURE_TYPE_APPLICATION_INFO, pNext=None,
                            pApplicationName=b"gbox-probe", applicationVersion=1,
                            pEngineName=b"none", engineVersion=1, apiVersion=(1 << 22))
    info = VkInstanceCreateInfo(sType=1, pNext=None, flags=0, pApplicationInfo=ctypes.pointer(app),
                                enabledLayerCount=0, ppEnabledLayerNames=None,
                                enabledExtensionCount=0, ppEnabledExtensionNames=None)
    instance = ctypes.c_void_p()
    result = vk.vkCreateInstance(ctypes.byref(info), None, ctypes.byref(instance))
    print("vkCreateInstance ->", result, "(0 = success)")
    if result != VK_SUCCESS:
        return 1
    count = ctypes.c_uint32(0)
    result = vk.vkEnumeratePhysicalDevices(instance, ctypes.byref(count), None)
    print("vkEnumeratePhysicalDevices ->", result, "devices:", count.value)
    if result == VK_SUCCESS and count.value:
        devices = (ctypes.c_void_p * count.value)()
        vk.vkEnumeratePhysicalDevices(instance, ctypes.byref(count), devices)
        print("device handles:", [hex(d or 0) for d in devices])
    vk.vkDestroyInstance(instance, None)
    return 0 if count.value else 2


if __name__ == "__main__":
    raise SystemExit(main())
