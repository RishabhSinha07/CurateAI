#!/usr/bin/env python3
"""
Simplified migration: Convert new knowledge graphs to minimal working versions.

This removes attributes, ingredients, and constraints temporarily and only keeps
problems and basic edges. This allows the domains to load and be functional
for routing and basic problem identification.
"""

import yaml
from pathlib import Path
from datetime import date


DOMAIN_PERSONAS = {
    "sexual_wellness_vitality": "You are a sexual wellness specialist. You help users find supplements for libido, performance, and fertility.",
    "hormonal_balance": "You are a hormonal health specialist. You help users with PCOS, PMS, menopause, and hormone balance.",
    "healthy_aging_longevity": "You are a longevity specialist. You help users find supplements for healthy aging and cellular health.",
    "muscle_strength_recovery": "You are a sports nutrition specialist. You help users find supplements for muscle building, strength, and recovery.",
    "sleep_stress_mental_calm": "You are a sleep and stress specialist. You help users find supplements for better sleep and stress management.",
    "brain_focus_memory": "You are a cognitive health specialist. You help users find supplements for brain function, focus, and memory.",
    "weight_management_metabolism": "You are a metabolic health specialist. You help users find supplements for healthy weight management.",
    "joint_bone_mobility": "You are a musculoskeletal specialist. You help users find supplements for bone health, joints, and mobility.",
}

# Domains that need simplification
DOMAINS_TO_SIMPLIFY = [
    "sexual_wellness_vitality",
    "hormonal_balance",
    "healthy_aging_longevity",
    "muscle_strength_recovery",
    "sleep_stress_mental_calm",
    "brain_focus_memory",
    "weight_management_metabolism",
    "joint_bone_mobility",
]


def simplify_graph(yaml_path: Path) -> bool:
    """Simplify a knowledge graph to minimal working version."""
    domain_slug = yaml_path.stem

    if domain_slug not in DOMAINS_TO_SIMPLIFY:
        print(f"Skipping {domain_slug} - not in simplification list")
        return False

    print(f"\nSimplifying: {yaml_path.name}")

    with open(yaml_path, 'r') as f:
        data = yaml.safe_load(f)

    # Create simplified structure
    simplified = {
        'metadata': {
            'domain': domain_slug,
            'version': '1.0.0',
            'created_at': str(date.today()),
            'description': f'Knowledge graph for {domain_slug.replace("_", " ").title()}',
            'display_name': domain_slug.replace('_', ' ').title(),
            'persona': DOMAIN_PERSONAS.get(domain_slug, f'You are a {domain_slug} specialist.'),
            'is_active': True,
            'parent_domain': None
        },
        'nodes': {
            'problems': [],
            'attributes': [],  # Empty for now
            'ingredients': [],  # Empty for now
            'constraints': [],  # Empty for now
            'questions': [],
            'products': [],
            'domains': [],
            'subdomains': []
        },
        'edges': []
    }

    # Extract problems
    problems_data = data.get('nodes', {}).get('problems', [])
    for problem in problems_data:
        simplified['nodes']['problems'].append({
            'id': problem['id'],
            'name': problem.get('name', problem['id']),
            'display_name': problem.get('display_name', problem['id'].replace('_', ' ').title()),
            'synonyms': problem.get('synonyms', [])[:5],  # Limit synonyms
            'severity_levels': ['mild', 'moderate', 'severe'],
            'description': problem.get('description', '')
        })

    print(f"  Extracted {len(simplified['nodes']['problems'])} problems")

    # Write simplified version
    with open(yaml_path, 'w') as f:
        yaml.dump(simplified, f, default_flow_style=False, sort_keys=False, width=120)

    print(f"  ✓ Simplified {yaml_path.name}")
    return True


def main():
    """Main simplification function."""
    print("="*70)
    print("Knowledge Graph Simplification")
    print("="*70)
    print("\nCreating minimal working versions of new domains...")
    print("(attributes, ingredients, constraints removed for now)\n")

    graphs_dir = Path(__file__).parent.parent / "app" / "knowledge" / "graphs"

    for domain in DOMAINS_TO_SIMPLIFY:
        yaml_path = graphs_dir / f"{domain}.yaml"
        if yaml_path.exists():
            try:
                simplify_graph(yaml_path)
            except Exception as e:
                print(f"  ✗ Error: {e}")
        else:
            print(f"  ✗ Not found: {yaml_path}")

    print("\n" + "="*70)
    print("Simplification complete!")
    print("="*70)
    print("\nThese domains now have:")
    print("  ✓ Problems with synonyms (for router)")
    print("  ✗ No attributes (interviewer will use generic questions)")
    print("  ✗ No ingredients (search will use product descriptions)")
    print("  ✗ No constraints (no safety filtering for now)")
    print("\nRestart the app to load the simplified graphs.")
    print("="*70 + "\n")


if __name__ == "__main__":
    main()
