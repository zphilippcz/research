fn main() {
    println!("cargo:rerun-if-changed=proto/idf.proto");
    match prost_build::compile_protos(&["proto/idf.proto"], &["proto"]) {
        Ok(_) => println!("Protobuf generated successfully."),
        Err(e) => eprintln!("Error generating protobuf: {:?}", e),
    }
}

