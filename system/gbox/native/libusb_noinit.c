/* gBox: LD_PRELOAD shim for Switch emulators on a Linux node (gbox.provision.switch_usb_shim builds it from this file
 * with the host's C compiler; never committed as a binary).
 *
 * libusb_init fails, so the emulator never enumerates USB devices. On the Spark (2026-10-26) every sysfs read on the
 * usb4 bus hung (bConfigurationValue_show). Citron NEO calls libusb_init on its main thread for its GameCube
 * adapter driver, so it never opened a window. Eden scans from a worker thread and was not affected. gBox sessions
 * drive the pad through the keyboard, so no USB controller is needed. The library has no libc dependency
 * (-nostdlib), so it loads under the AppImage's own dynamic loader (sharun: SHARUN_ALLOW_LD_PRELOAD=1). */
typedef struct libusb_context libusb_context;

#define LIBUSB_ERROR_OTHER (-99)

int libusb_init(libusb_context **ctx) {
    (void)ctx;
    return LIBUSB_ERROR_OTHER;
}

int libusb_init_context(libusb_context **ctx, const void *options, int num_options) {
    (void)ctx;
    (void)options;
    (void)num_options;
    return LIBUSB_ERROR_OTHER;
}
