#!/usr/bin/env python3
import json
import re
import sys
import os
from pathlib import Path

# Known hobbies or activities that shouldn't be parsed as person nodes
HOBBIES = {"one wheel", "dragon boat"}

# Relationship terms that need to be inverted in name extraction
RELATIONSHIP_TERMS = {"roommate", "friend", "cousin", "mom", "dad", "sister", "brother", "colleague", "boss"}

def normalize_id(name):
    """Normalize a name to a clean, unique identifier."""
    # Convert to lowercase, replace spaces/dashes with underscores, keep only alphanumeric and underscores
    clean = name.lower().strip()
    clean = re.sub(r'[\s\-]+', '_', clean)
    clean = re.sub(r'[^a-z0-9_]', '', clean)
    return clean

def parse_node_string(node_str):
    """Parse a single node string into id, name, and metadata list."""
    node_str = node_str.strip()
    if not node_str:
        return None
        
    metadata = []
    
    # 0. Extract hobby/activity metadata
    found_hobbies = []
    for hobby in HOBBIES:
        if hobby in node_str.lower():
            found_hobbies.append(hobby)
            pattern = re.compile(re.escape(hobby), re.IGNORECASE)
            node_str = pattern.sub('', node_str).strip()
            
    # Clean up spaces
    node_str = ' '.join(node_str.split())
    if not node_str:
        return None
        
    # 1. Extract metadata from parentheses (e.g., "Ryan (Oregon)" -> "Oregon")
    parentheticals = re.findall(r'\(([^)]+)\)', node_str)
    clean_name = re.sub(r'\([^)]+\)', '', node_str).strip()
    
    # 2. Handle list markers (e.g., "- sachin")
    if clean_name.startswith('-'):
        clean_name = clean_name.lstrip('-').strip()
        
    # 3. Extract leading numeric codes as metadata (e.g., "102 henry" -> "henry", metadata "102")
    num_match = re.match(r'^(\d+)\s+(.+)$', clean_name)
    if num_match:
        metadata.append(num_match.group(1))
        clean_name = num_match.group(2).strip()
        
    # Clean up multiple internal spaces
    clean_name = ' '.join(clean_name.split())
    
    # 4. Relationship term inversion: e.g., "roommate (Clarissa)" -> name "Clarissa", metadata "roommate"
    if clean_name.lower() in RELATIONSHIP_TERMS and len(parentheticals) == 1:
        rel_term = clean_name
        clean_name = parentheticals[0].strip()
        metadata.append(rel_term.lower())
    else:
        for p in parentheticals:
            metadata.append(p.strip())
            
    # Add extracted hobbies to metadata
    for hobby in found_hobbies:
        if hobby not in metadata:
            metadata.append(hobby)
            
    # Generate clean ID
    node_id = normalize_id(clean_name)
    if not node_id:
        return None
        
    # Format display name: title-case if it's completely lowercase
    display_name = clean_name
    if display_name.islower():
        display_name = display_name.title()
        
    return {
        "id": node_id,
        "name": display_name,
        "metadata": metadata
    }

def extract_entities_from_string(s, is_edge_target=False):
    """Split a string by delimiters and parse individual entities."""
    s = s.strip()
    if not s:
        return []
        
    # Split by comma or plus
    parts = re.split(r'[,+]', s)
    results = []
    
    for part in parts:
        part = part.strip()
        if not part:
            continue
            
        if is_edge_target:
            # Split by space, but keep parenthetical blocks attached to their preceding words
            subparts = re.findall(r'\S+\s*\([^)]+\)|\S+', part)
            
            # Recombine known multi-word exception tokens (e.g., ["one", "wheel"] -> ["one wheel"])
            recombined = []
            i = 0
            while i < len(subparts):
                if i < len(subparts) - 1:
                    combined = f"{subparts[i]} {subparts[i+1]}".lower()
                    if combined in HOBBIES:
                        recombined.append(f"{subparts[i]} {subparts[i+1]}")
                        i += 2
                        continue
                recombined.append(subparts[i])
                i += 1
            
            for subpart in recombined:
                parsed = parse_node_string(subpart)
                if parsed:
                    results.append(parsed)
        else:
            # If not an edge target, check for the special case of 4 space-separated words (e.g., "johnathon rong brandon long")
            # without punctuation, which usually indicates two Full Names (First Last First Last)
            words = part.split()
            if len(words) == 4 and not re.search(r'[()\-]', part):
                part1 = f"{words[0]} {words[1]}"
                part2 = f"{words[2]} {words[3]}"
                for subpart in [part1, part2]:
                    parsed = parse_node_string(subpart)
                    if parsed:
                        results.append(parsed)
            else:
                parsed = parse_node_string(part)
                if parsed:
                    results.append(parsed)
                    
    return results

def is_context_header(line):
    """Determine if a line represents a group/context header."""
    line_lower = line.lower()
    if line_lower.endswith('#name'):
        return True
    if line_lower.endswith(':'):
        return True
    if 'club' in line_lower:
        return True
    if re.match(r'^(winter|spring|summer|fall)\s+\d{4}$', line_lower):
        return True
    if 'dsc' in line_lower and ('+' in line_lower or re.search(r'\d+', line_lower)) and not ('--' in line_lower):
        return True
    return False

def clean_context_name(line):
    """Extract and clean the context/group name from a header line."""
    line = line.strip()
    if line.lower().endswith('#name'):
        line = line[:-5].strip()
    elif line.endswith(':'):
        line = line[:-1].strip()
    return line

def is_noise_line(line):
    """Determine if a line is a note, task, or placeholder that should be ignored."""
    line_clean = line.strip()
    if not line_clean:
        return True
        
    # Separator is handled in the main parser loop
    if re.match(r'^---+$', line_clean):
        return False
        
    # Ends with punctuation indicating a note/phrase rather than names
    if line_clean.endswith(('!', '?')):
        return True
        
    # Common single-word notes/placeholders
    noise_words = {"same", "ditto", "none", "n/a", "tbd", "todo", "temp"}
    if line_clean.lower() in noise_words:
        return True
        
    # Action items/sentences (e.g., "Write inquiry to recreation")
    line_lower = line_clean.lower()
    action_verbs = {"write", "send", "call", "meet", "email", "buy", "check", "read"}
    words = line_lower.split()
    if len(words) > 1:
        if words[0] in action_verbs:
            return True
        sentence_indicators = {"to", "for", "with", "about", "from", "the", "and"}
        # Only treat as sentence if it doesn't contain social graph symbols
        if not any(marker in line_clean for marker in ['-->', '->', '+', ',']):
            if any(w in sentence_indicators for w in words):
                return True
                
    return False

def parse_notes(file_path):
    """Parse notes file and return a dictionary of nodes and edges."""
    if not Path(file_path).exists():
        print(f"Error: File {file_path} does not exist.")
        sys.exit(1)
        
    nodes_dict = {}
    edges_set = set()
    
    current_context = None
    last_sources = []
    
    # Using utf-8-sig automatically strips the UTF-8 BOM if present
    with open(file_path, 'r', encoding='utf-8-sig') as f:
        lines = f.readlines()
        
    for line_num, line in enumerate(lines, 1):
        line_clean = line.strip()
        if not line_clean:
            continue
            
        if is_noise_line(line_clean):
            continue
            
        # Context reset or page separator
        if re.match(r'^---+$', line_clean):
            current_context = None
            last_sources = []
            continue
            
        # Handle inline context header (e.g., "gunn: sophia")
        if ':' in line_clean and not line_clean.endswith(':'):
            parts = line_clean.split(':', 1)
            context_name = parts[0].strip()
            line_clean = parts[1].strip()
            
            current_context = context_name
            last_sources = []
            
            group_id = normalize_id(context_name)
            if group_id not in nodes_dict:
                nodes_dict[group_id] = {
                    "id": group_id,
                    "name": context_name,
                    "type": "group",
                    "metadata": [],
                    "contexts": []
                }
            if not line_clean:
                continue
            
        # Check if line is a context header
        if is_context_header(line_clean):
            context_name = clean_context_name(line_clean)
            current_context = context_name
            last_sources = []
            
            # Add the context group itself as a group node
            group_id = normalize_id(context_name)
            if group_id not in nodes_dict:
                nodes_dict[group_id] = {
                    "id": group_id,
                    "name": context_name,
                    "type": "group",
                    "metadata": [],
                    "contexts": []
                }
            continue
            
        # Parse edge: check if line is an explicit or implicit introduction edge
        # Supports: '-->', '->', '-- >'
        edge_match = re.search(r'^(.+?)\s*--?\s*>\s*(.+)$', line_clean)
        implicit_match = re.search(r'^\s*--?\s*>\s*(.+)$', line_clean)
        
        # Check if target is a known hobby/activity
        is_hobby_edge = False
        hobby_name = None
        if edge_match:
            target_candidate = edge_match.group(2).strip().lower()
            if target_candidate in HOBBIES:
                is_hobby_edge = True
                hobby_name = target_candidate
        elif implicit_match:
            target_candidate = implicit_match.group(1).strip().lower()
            if target_candidate in HOBBIES:
                is_hobby_edge = True
                hobby_name = target_candidate
                
        if is_hobby_edge:
            if edge_match:
                source_str = edge_match.group(1)
                sources = extract_entities_from_string(source_str, is_edge_target=False)
                for s in sources:
                    s_id = s["id"]
                    if s_id not in nodes_dict:
                        nodes_dict[s_id] = {
                            "id": s_id,
                            "name": s["name"],
                            "type": "person",
                            "metadata": s["metadata"],
                            "contexts": [current_context] if current_context else []
                        }
                    if hobby_name not in nodes_dict[s_id]["metadata"]:
                        nodes_dict[s_id]["metadata"].append(hobby_name)
                    if current_context and current_context not in nodes_dict[s_id]["contexts"]:
                        nodes_dict[s_id]["contexts"].append(current_context)
                last_sources = sources
            elif implicit_match:
                for s in last_sources:
                    s_id = s["id"]
                    if s_id in nodes_dict:
                        if hobby_name not in nodes_dict[s_id]["metadata"]:
                            nodes_dict[s_id]["metadata"].append(hobby_name)
            continue
            
        if implicit_match:
            # Implicit introduction from last source(s)
            target_str = implicit_match.group(1)
            targets = extract_entities_from_string(target_str, is_edge_target=True)
            
            if not last_sources:
                # No active source, parse as standalone nodes
                for t in targets:
                    t_id = t["id"]
                    if t_id not in nodes_dict:
                        nodes_dict[t_id] = {
                            "id": t_id,
                            "name": t["name"],
                            "type": "person",
                            "metadata": t["metadata"],
                            "contexts": [current_context] if current_context else []
                        }
                    else:
                        for m in t["metadata"]:
                            if m not in nodes_dict[t_id]["metadata"]:
                                nodes_dict[t_id]["metadata"].append(m)
                        if current_context and current_context not in nodes_dict[t_id]["contexts"]:
                            nodes_dict[t_id]["contexts"].append(current_context)
            else:
                # Create edges from all last sources to all targets
                for s in last_sources:
                    for t in targets:
                        t_id = t["id"]
                        # Ensure target node exists
                        if t_id not in nodes_dict:
                            nodes_dict[t_id] = {
                                "id": t_id,
                                "name": t["name"],
                                "type": "person",
                                "metadata": t["metadata"],
                                "contexts": [current_context] if current_context else []
                            }
                        else:
                            for m in t["metadata"]:
                                if m not in nodes_dict[t_id]["metadata"]:
                                    nodes_dict[t_id]["metadata"].append(m)
                            if current_context and current_context not in nodes_dict[t_id]["contexts"]:
                                nodes_dict[t_id]["contexts"].append(current_context)
                                
                        edges_set.add((s["id"], t_id, "introduction"))
            continue
            
        elif edge_match:
            # Explicit introduction: source --> target
            source_str = edge_match.group(1)
            target_str = edge_match.group(2)
            
            sources = extract_entities_from_string(source_str, is_edge_target=False)
            targets = extract_entities_from_string(target_str, is_edge_target=True)
            
            # Register sources
            for s in sources:
                s_id = s["id"]
                if s_id not in nodes_dict:
                    nodes_dict[s_id] = {
                        "id": s_id,
                        "name": s["name"],
                        "type": "person",
                        "metadata": s["metadata"],
                        "contexts": [current_context] if current_context else []
                    }
                else:
                    for m in s["metadata"]:
                        if m not in nodes_dict[s_id]["metadata"]:
                            nodes_dict[s_id]["metadata"].append(m)
                    if current_context and current_context not in nodes_dict[s_id]["contexts"]:
                        nodes_dict[s_id]["contexts"].append(current_context)
            
            # Register targets and add edges
            for s in sources:
                for t in targets:
                    t_id = t["id"]
                    if t_id not in nodes_dict:
                        nodes_dict[t_id] = {
                            "id": t_id,
                            "name": t["name"],
                            "type": "person",
                            "metadata": t["metadata"],
                            "contexts": [current_context] if current_context else []
                        }
                    else:
                        for m in t["metadata"]:
                            if m not in nodes_dict[t_id]["metadata"]:
                                nodes_dict[t_id]["metadata"].append(m)
                        if current_context and current_context not in nodes_dict[t_id]["contexts"]:
                            nodes_dict[t_id]["contexts"].append(current_context)
                            
                    edges_set.add((s["id"], t_id, "introduction"))
                    
            last_sources = sources
            continue
            
        # Parse standard nodes (no edges, no header)
        parsed_nodes = extract_entities_from_string(line_clean, is_edge_target=False)
        for node in parsed_nodes:
            node_id = node["id"]
            if node_id not in nodes_dict:
                nodes_dict[node_id] = {
                    "id": node_id,
                    "name": node["name"],
                    "type": "person",
                    "metadata": node["metadata"],
                    "contexts": [current_context] if current_context else []
                }
            else:
                for m in node["metadata"]:
                    if m not in nodes_dict[node_id]["metadata"]:
                        nodes_dict[node_id]["metadata"].append(m)
                if current_context and current_context not in nodes_dict[node_id]["contexts"]:
                    nodes_dict[node_id]["contexts"].append(current_context)
                    
            # If current_context is active, we can record the member_of edge
            if current_context:
                group_id = normalize_id(current_context)
                edges_set.add((node_id, group_id, "membership"))

    # Convert nodes dict to list
    nodes_list = list(nodes_dict.values())
    
    # Convert edges set to list of dicts
    edges_list = []
    for source, target, edge_type in edges_set:
        edges_list.append({
            "source": source,
            "target": target,
            "type": edge_type
        })
        
    return {
        "nodes": nodes_list,
        "edges": edges_list
    }

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    input_file = os.path.join(script_dir, "sample_notes.txt")
    output_file = os.path.join(script_dir, "graph_data.json")
    
    if len(sys.argv) > 1:
        input_file = sys.argv[1]
    if len(sys.argv) > 2:
        output_file = sys.argv[2]
        
    print(f"Parsing {input_file}...")
    graph = parse_notes(input_file)
    
    print(f"Writing graph data to {output_file}...")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(graph, f, indent=2, ensure_ascii=False)
        
    print("\nSummary of Extracted Graph:")
    print(f"Total Nodes: {len(graph['nodes'])}")
    print(f"Total Edges: {len(graph['edges'])}")
    
    # Show statistics
    types = {}
    for node in graph['nodes']:
        types[node['type']] = types.get(node['type'], 0) + 1
    print("\nNodes by type:")
    for t, count in types.items():
        print(f"  - {t}: {count}")
        
    edge_types = {}
    for edge in graph['edges']:
        edge_types[edge['type']] = edge_types.get(edge['type'], 0) + 1
    print("\nEdges by type:")
    for t, count in edge_types.items():
        print(f"  - {t}: {count}")

if __name__ == "__main__":
    main()
