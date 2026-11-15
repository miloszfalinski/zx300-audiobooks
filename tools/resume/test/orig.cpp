// Test stand-in for Sony's libScreenshotShared.so: one exported function.
#include <cstdio>
namespace screenshot { __attribute__((visibility("default"))) void screenshot() { std::puts("MOCK: screenshot::screenshot() reached the original library"); } }
