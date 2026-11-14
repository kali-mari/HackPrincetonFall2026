// Private pipe protocol: one raw f32/16 kHz mono file path per line; JSON replies.
// Text travels only through the parent's pipe, never a public log or result file.
#include "whisper.h"
#include "ggml-backend.h"
#include <cstring>
#include <sys/resource.h>
#include <chrono>
#include <fstream>
#include <iostream>
#include <iomanip>
#include <sstream>
#include <vector>
#include <stdexcept>
using Clock = std::chrono::steady_clock;
static double elapsed(Clock::time_point t) {
    return std::chrono::duration<double>(Clock::now()-t).count();
}
static double cpu() {
    rusage r{}; getrusage(RUSAGE_SELF, &r);
    return r.ru_utime.tv_sec+r.ru_utime.tv_usec/1e6+r.ru_stime.tv_sec+r.ru_stime.tv_usec/1e6;
}
static long peak() {
    rusage r{}; getrusage(RUSAGE_SELF, &r);
#ifdef __APPLE__
    return r.ru_maxrss;
#else
    return r.ru_maxrss*1024L;
#endif
}
static std::string quote(const std::string &s) {
    std::ostringstream o; o << '"';
    for (unsigned char c : s) {
        if (c == '"' || c == '\\') o << '\\' << c;
        else if (c < 32) o << "\\u" << std::hex << std::setw(4) << std::setfill('0') << int(c);
        else o << c;
    }
    o << '"'; return o.str();
}
static void quiet(enum ggml_log_level, const char *msg, void *) {
    // Only fixed backend/init diagnostics may reach stderr. Never decoder text.
    if (std::strstr(msg, "ggml_vulkan:") || std::strstr(msg, "whisper_backend_init_gpu:") ||
        std::strstr(msg, "buffer size") || std::strstr(msg, "compute buffer") ||
        std::strstr(msg, "using Vulkan") || std::strstr(msg, "Vulkan0 total size")) std::cerr << msg;
}
int main(int argc, char **argv) {
    if (argc != 4) return 2;
    whisper_log_set(quiet, nullptr);
    const int threads = std::stoi(argv[2]);
    if (threads < 1) return 2;
    auto cp = whisper_context_default_params(); cp.use_gpu = std::string(argv[3]) == "vulkan"; cp.flash_attn = false;
    auto start = Clock::now(); double c0 = cpu();
    auto *ctx = whisper_init_from_file_with_params(argv[1], cp);
    if (!ctx) return 3;
    std::cout << std::setprecision(12) << "{\"load_s\":" << elapsed(start)
              << ",\"gpu_requested\":" << (cp.use_gpu ? "true" : "false") << ",\"cpu_s\":" << cpu()-c0 << ",\"peak_rss_bytes\":" << peak() << "}" << std::endl;
    std::cerr << "BENCH_BACKENDS:";
    for (size_t i=0; i<ggml_backend_dev_count(); ++i) std::cerr << " " << ggml_backend_dev_name(ggml_backend_dev_get(i));
    std::cerr << std::endl;
    std::string path;
    while (std::getline(std::cin, path)) {
        std::ifstream f(path, std::ios::binary | std::ios::ate);
        auto size = f.tellg();
        if (!f || size <= 0 || size % 4 != 0 || size / 4 > 16000LL*3600) { whisper_free(ctx); return 4; }
        std::vector<float> pcm(static_cast<size_t>(size)/4);
        f.seekg(0); f.read(reinterpret_cast<char *>(pcm.data()), size);
        if (!f) { whisper_free(ctx); return 4; }
        auto p = whisper_full_default_params(WHISPER_SAMPLING_GREEDY);
        p.n_threads = threads; p.language = "en"; p.translate = false;
        p.no_context = true; p.single_segment = false;
        p.print_realtime = false; p.print_progress = false;
        p.print_timestamps = false; p.print_special = false;
        p.temperature = 0.0f; p.temperature_inc = 0.0f; p.greedy.best_of = 1;
        start = Clock::now(); c0 = cpu();
        int rc = whisper_full(ctx, p, pcm.data(), int(pcm.size()));
        double seconds = elapsed(start), cpu_seconds = cpu()-c0;
        if (rc) { whisper_free(ctx); return 5; }
        std::string text;
        for (int i=0; i<whisper_full_n_segments(ctx); ++i) text += whisper_full_get_segment_text(ctx, i);
        std::cout << "{\"inference_s\":" << seconds << ",\"cpu_s\":" << cpu_seconds
                  << ",\"peak_rss_bytes\":" << peak() << ",\"text\":" << quote(text) << "}" << std::endl;
    }
    whisper_free(ctx); return 0;
}
