extern "C" {
    fn p94_hallo() -> i32;
}

fn main() {
    println!("hallo {}", unsafe { p94_hallo() });
}
