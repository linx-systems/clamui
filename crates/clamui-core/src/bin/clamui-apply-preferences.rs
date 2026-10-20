fn main() {
    let args = std::env::args().skip(1).collect::<Vec<_>>();
    std::process::exit(clamui_core::privileged::run_helper(&args));
}
