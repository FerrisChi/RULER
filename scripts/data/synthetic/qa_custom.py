# Copyright (c) 2024, NVIDIA CORPORATION.  All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License

"""
Create a dataset jsonl file for QA task.

python qa.py \
    --save_dir=./ \
    --save_name=niah_single \
    --tokenizer_path=tokenizer.model \
    --tokenizer_type=nemo \
    --max_seq_length=4096 \
    --tokens_to_generate=128 \
    --num_samples=10 \
    --template="Answer the question based on the given documents. Only give me the answer and do not output any other words.\n\nThe following are given documents.\n\n{context}\n\nAnswer the question based on the given documents. Only give me the answer and do not output any other words.\n\nQuestion: {query} Answer:"
"""
import os
import re
import json
import argparse
from pathlib import Path
from tqdm import tqdm
import random
import numpy as np
import jsonlines
# from nemo.collections.asr.parts.utils.manifest_utils import read_manifest, write_manifest
import sys
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")) 
from tokenizer import select_tokenizer


parser = argparse.ArgumentParser()
# Basic Configurations
parser.add_argument("--save_dir", type=Path, required=True, help='dataset folder to save dataset')
parser.add_argument("--save_name", type=str, required=True, help='name of the save dataset jsonl file')
parser.add_argument("--subset", type=str, default='validation', help='Options: validation or test')
parser.add_argument("--tokenizer_path", type=str, required=True, help='path to the tokenizer model')
parser.add_argument("--tokenizer_type",  type=str, default='nemo', help='[Options] nemo, hf, openai.')
parser.add_argument("--max_seq_length", type=int, required=True, help='max sequence length including all input tokens and generated tokens.')
parser.add_argument("--tokens_to_generate", type=int, required=True, help='expected generated token amount.')
parser.add_argument("--num_samples", type=int, required=True, help='number of samples to generate')
parser.add_argument("--pre_samples", type=int, default=0, help='number of samples are already generated')
parser.add_argument("--random_seed", type=int, default=42)
parser.add_argument("--template", type=str, required=True, help='prompt template')
parser.add_argument("--remove_newline_tab", action='store_true', help='remove `\n` and `\t` in all strings.')
parser.add_argument("--position", type=str, default='uniform', help='[Options] head, tail, uniform.')

# Complexity Configurations
parser.add_argument("--dataset", type=str, required=True, help='dataset file')

args = parser.parse_args()
random.seed(args.random_seed)
np.random.seed(args.random_seed)

# Load Tokenizer
TOKENIZER = select_tokenizer(args.tokenizer_type, args.tokenizer_path)

# Read SQuAD QA dataset
def read_squad(file):
    with open(file) as f:
        data = json.load(f)
        
    total_docs = [p['context'] for d in data['data'] for p in d['paragraphs']]
    total_docs = sorted(list(set(total_docs)))
    total_docs_dict = {c: idx for idx, c in enumerate(total_docs)}

    total_qas = []
    for d in data['data']:
        more_docs = [total_docs_dict[p['context']] for p in d['paragraphs']]
        for p in d['paragraphs']:
            for qas in p['qas']:
                if not qas['is_impossible']:
                    total_qas.append({
                        'query': qas['question'],
                        'outputs': [a['text'] for a in qas['answers']],
                        'context': [total_docs_dict[p['context']]],
                        'more_context': [idx for idx in more_docs if idx != total_docs_dict[p['context']]]
                    })
                        
    return total_qas, total_docs

# Read Hotpot QA dataset
def read_hotpotqa(file):
    with open(file) as f:
        data = json.load(f)

    total_docs = [f"{t}\n{''.join(p)}" for d in data for t, p in d['context']]
    total_docs = sorted(list(set(total_docs)))
    total_docs_dict = {c: idx for idx, c in enumerate(total_docs)}
    
    total_qas = []
    for d in data:
        facts = []
        facts_text = []
        context = [total_docs_dict[f"{t}\n{''.join(p)}"] for t, p in d['context']]
        for fact in d['supporting_facts']:
            fact_title = fact[0]  # The title of the document
            fact_sent_idx = fact[1]  # The sentence index within that document
            
            # Find the corresponding context with matching title
            for ctx in d['context']:
                ctx_title = ctx[0]
                ctx_sentences = ctx[1]
                
                # If we found the right document
                if fact_title == ctx_title:
                    # Make sure the sentence index is valid
                    if fact_sent_idx < len(ctx_sentences):
                        fact_id = total_docs_dict[f"{fact_title}\n{''.join(ctx_sentences)}"]
                        facts.append(fact_id)
                        facts_text.append(f"{ctx_sentences[fact_sent_idx]}")
                        break
        total_qas.append({
            'query': d['question'],
            'outputs': [d['answer']],
            'context': context,
            'facts': facts,
            'facts_text': facts_text
        })
        
    return total_qas, total_docs


DOCUMENT_PROMPT = "Document {i}:\n{document}"
if args.dataset == 'squad':
    QAS, DOCS = read_squad(os.path.join(os.path.dirname(os.path.abspath(__file__)), "json/squad.json"))
elif args.dataset == 'hotpotqa':
    QAS, DOCS = read_hotpotqa(os.path.join(os.path.dirname(os.path.abspath(__file__)), "json/hotpotqa.json"))
else:
    raise NotImplementedError(f'{args.dataset} is not implemented.')


def generate_input_output(index, num_docs):
    curr_q = QAS[index]['query']
    curr_a = QAS[index]['outputs']
    curr_docs = QAS[index]['context']  # List of document indices
    curr_more = QAS[index].get('more_context', [])
    curr_facts = QAS[index]['facts']  # List of document indices, similar to curr_docs
    curr_facts_text = QAS[index]['facts_text'] # List of fact text, following the order of curr_facts
    
    # First, determine which document indices we'll use
    if num_docs < len(DOCS):
        if (num_docs - len(curr_docs)) > len(curr_more):
            addition_docs = [i for i, d in enumerate(DOCS) if i not in curr_docs + curr_more]
            all_doc_indices = curr_docs + curr_more + random.sample(addition_docs, max(0, num_docs - len(curr_docs) - len(curr_more)))
        else:
            all_doc_indices = curr_docs + random.sample(curr_more, max(0, num_docs - len(curr_docs)))
    else:
        all_doc_indices = list(range(len(DOCS)))
    
    # Create a mapping from original document indices to their content
    doc_content_map = {idx: DOCS[idx] for idx in all_doc_indices}
    
    # Create a list of document indices to be used in the final context
    final_doc_indices = list(all_doc_indices)
    
    # Shuffle the document indices based on position argument
    if args.position == 'head':
        # Randomly scatter curr_docs within the top 15% of the context
        if curr_docs:
            # Remove curr_docs from final_doc_indices to avoid duplicates
            remaining_indices = [idx for idx in final_doc_indices if idx not in curr_docs]
            # Shuffle the remaining indices
            random.Random(args.random_seed).shuffle(remaining_indices)
            
            # Calculate the number of positions in the top 15%
            top_positions = max(1, int(num_docs * 0.15))
            
            # Shuffle curr_docs to randomize their order
            curr_docs_shuffled = curr_docs.copy()
            random.Random(args.random_seed).shuffle(curr_docs_shuffled)
            
            # Create the final document indices by:
            # 1. Taking some of the remaining indices for the beginning positions
            # 2. Interleaving the curr_docs within the top 15%
            # 3. Adding the rest of the remaining indices
            
            # Ensure we don't try to sample more positions than are available
            num_docs_to_place = min(len(curr_docs), top_positions)
            
            # If we have more curr_docs than top positions, truncate curr_docs
            if len(curr_docs) > top_positions:
                curr_docs_shuffled = curr_docs_shuffled[:top_positions]
            
            # Randomly determine positions for curr_docs within the top 15%
            positions = sorted(random.Random(args.random_seed).sample(range(top_positions), num_docs_to_place))
            
            # Build the final document indices
            final_doc_indices = []
            remaining_idx = 0
            
            for i in range(top_positions):
                if i in positions:
                    # Add a curr_doc at this position
                    curr_doc_idx = positions.index(i)
                    final_doc_indices.append(curr_docs_shuffled[curr_doc_idx])
                else:
                    # Add a remaining document
                    final_doc_indices.append(remaining_indices[remaining_idx])
                    remaining_idx += 1
            
            # Add the rest of the remaining indices
            final_doc_indices.extend(remaining_indices[remaining_idx:num_docs - len(curr_docs)])
        else:
            # If no curr_docs, just shuffle
            random.Random(args.random_seed).shuffle(final_doc_indices)
    elif args.position == 'tail':
        # Randomly scatter curr_docs within the bottom 15% of the context
        if curr_docs:
            # Remove curr_docs from final_doc_indices to avoid duplicates
            remaining_indices = [idx for idx in final_doc_indices if idx not in curr_docs]
            # Shuffle the remaining indices
            random.Random(args.random_seed).shuffle(remaining_indices)
            
            # Calculate the number of positions in the bottom 15%
            bottom_positions = max(1, int(num_docs * 0.15))
            start_idx = num_docs - bottom_positions
            
            # Shuffle curr_docs to randomize their order
            curr_docs_shuffled = curr_docs.copy()
            random.Random(args.random_seed).shuffle(curr_docs_shuffled)
            
            # Take the first part of remaining indices
            final_doc_indices = remaining_indices[:start_idx]
            
            # Ensure we don't try to sample more positions than are available
            num_docs_to_place = min(len(curr_docs), bottom_positions)
            
            # If we have more curr_docs than bottom positions, truncate curr_docs
            if len(curr_docs) > bottom_positions:
                curr_docs_shuffled = curr_docs_shuffled[:bottom_positions]
            
            # Randomly determine positions for curr_docs within the bottom 15%
            relative_positions = sorted(random.Random(args.random_seed).sample(range(bottom_positions), num_docs_to_place))
            
            # Map relative positions to absolute positions
            positions = [start_idx + pos for pos in relative_positions]
            
            # Fill the bottom 15% with a mix of remaining indices and curr_docs
            bottom_part = []
            remaining_idx = 0
            
            for i in range(start_idx, num_docs):
                if i in positions:
                    # Add a curr_doc at this position
                    curr_doc_idx = positions.index(i)
                    bottom_part.append(curr_docs_shuffled[curr_doc_idx])
                else:
                    # Add a remaining document
                    bottom_part.append(remaining_indices[remaining_idx])
                    remaining_idx += 1
            
            final_doc_indices.extend(bottom_part)
        else:
            # If no curr_docs, just shuffle
            random.Random(args.random_seed).shuffle(final_doc_indices)
    else:  # 'uniform' or default
        # Just shuffle all indices
        random.Random(args.random_seed).shuffle(final_doc_indices)
    
    # Ensure we only use num_docs documents
    final_doc_indices = final_doc_indices[:num_docs]
    
    # Create a mapping from original document indices to their new positions (1-indexed)
    doc_position_map = {idx: i+1 for i, idx in enumerate(final_doc_indices)}
    
    # Map the document indices to their content and format with new positions
    all_docs = [doc_content_map[idx] for idx in final_doc_indices]
    context = '\n\n'.join([DOCUMENT_PROMPT.format(i=i+1, document=d) for i, d in enumerate(all_docs)])
    
    # Get the fact document IDs that are in the final context
    # Filter curr_facts to only include those that are in the final context
    fact_doc_ids = []
    filtered_facts_text = []
    
    # Create a mapping between original fact_ids and their corresponding facts_text
    fact_id_to_text = {fact_id: text for fact_id, text in zip(curr_facts, curr_facts_text)}
    
    for fact_id in curr_facts:
        if fact_id in doc_position_map:
            # Map the original document index to its new position in the context
            fact_doc_ids.append(doc_position_map[fact_id])
            # Keep track of the corresponding fact text
            filtered_facts_text.append(fact_id_to_text[fact_id])
    
    # Sort the fact document IDs for consistency, and reorder facts_text to match
    if fact_doc_ids:
        # Create pairs of (fact_doc_id, fact_text) for sorting
        paired_facts = list(zip(fact_doc_ids, filtered_facts_text))
        # Sort by fact_doc_id
        paired_facts.sort(key=lambda x: x[0])
        # Unzip the sorted pairs
        fact_doc_ids, filtered_facts_text = zip(*paired_facts) if paired_facts else ([], [])
        # Convert back to lists
        fact_doc_ids = list(fact_doc_ids)
        filtered_facts_text = list(filtered_facts_text)
    
    input_text = args.template.format(
        context=context, 
        query=curr_q
    )
    return input_text, curr_q, curr_a, fact_doc_ids, filtered_facts_text


def generate_samples(num_samples: int, max_seq_length: int, save_dir: str, incremental: int = 3): 
    
    write_jsons = []
    tokens_to_generate = args.tokens_to_generate
    
    # Find the perfect num_docs
    num_docs = incremental
    
    total_tokens = 0  # Track the total tokens generated for this example
    while total_tokens + tokens_to_generate < max_seq_length :  
        input_text, query, answer, curr_facts, curr_facts_text = generate_input_output(0, num_docs)
        # Calculate the number of tokens in the example
        total_tokens = len(TOKENIZER.text_to_tokens(input_text + f' {answer}'))
        print(f'Max length {max_seq_length} | Current length {total_tokens + tokens_to_generate} | Docs: {num_docs}')
        if total_tokens + tokens_to_generate > max_seq_length:
            num_docs -= incremental
            break
            
        num_docs += incremental
        if num_docs > len(DOCS):
            num_docs = len(DOCS)
            break
    print('Number of documents:', num_docs)
    
    # Generate samples
    for index in tqdm(range(num_samples)):
        used_docs = num_docs
        while(True):
            try:
                input_text, query, answer, curr_facts, curr_facts_text = generate_input_output(index + args.pre_samples, used_docs)
                length = len(TOKENIZER.text_to_tokens(input_text)) + tokens_to_generate
                assert length <= max_seq_length, f"{length} exceeds max_seq_length."
                break
            except:
                if used_docs > incremental:
                    used_docs -= incremental
        
        if args.remove_newline_tab:
            input_text = ' '.join(input_text.replace('\n', ' ').replace('\t', ' ').strip().split())
        
        formatted_output = {
            "index": index,
            "input": input_text,
            "query": query,
            "outputs": answer,
            "length": length,
            "fact_doc_ids": curr_facts,
            "facts_text": curr_facts_text
        }
        write_jsons.append(formatted_output)

    return write_jsons


def main():
    save_file = args.save_dir / f'{args.save_name}' / f'{args.subset}.jsonl'
    save_file.parent.mkdir(parents=True, exist_ok=True)

    write_jsons = generate_samples(
        num_samples=args.num_samples, 
        max_seq_length=args.max_seq_length, 
        save_dir=args.save_dir
    )
    
    with jsonlines.open(save_file, mode='w') as writer:
        writer.write_all(write_jsons)
    # write_manifest(save_file, write_jsons)

if __name__=="__main__":
    main()
