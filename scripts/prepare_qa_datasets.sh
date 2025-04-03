#!/bin/bash
# Script to generate multiple NIAH datasets with different configurations
# Copyright (c) 2024, User

# Set common parameters
SAVE_DIR="./qa_datasets"
TOKENIZER_PATH="BAAI/bge-m3"  # Using the common GPT-2 tokenizer from Hugging Face
TOKENIZER_TYPE="hf"    # Hugging Face tokenizer type
MAX_SEQ_LENGTH=65536
MODEL_TEMPLATE_TYPE="base"
NUM_SAMPLES=100
BENCHMARK="synthetic"

# Create the save directory if it doesn't exist
mkdir -p $SAVE_DIR

# Function to run prepare.py with given parameters
run_prepare() {
    local task=$1
    local custom_args=$2
    
    echo "Preparing dataset: $task"
    
    python scripts/data/prepare.py \
        --save_dir $SAVE_DIR \
        --benchmark $BENCHMARK \
        --task $task \
        --subset "dataset" \
        --tokenizer_path $TOKENIZER_PATH \
        --tokenizer_type $TOKENIZER_TYPE \
        --max_seq_length $MAX_SEQ_LENGTH \
        --model_template_type $MODEL_TEMPLATE_TYPE \
        --num_samples $NUM_SAMPLES \
        $custom_args
        
    echo "Completed dataset: $task"
    echo "------------------------"
}

# Generate standard QA datasets from synthetic.yaml
echo "Generating standard QA datasets..."

run_prepare "qa_head" ""
run_prepare "qa_tail" ""
run_prepare "qa_uniform" ""

echo "All datasets have been prepared successfully!"
echo "Datasets are available in: $SAVE_DIR"
