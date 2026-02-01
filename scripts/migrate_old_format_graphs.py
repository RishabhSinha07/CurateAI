#!/usr/bin/env python3
"""
Migrate old-format knowledge graphs to new format.

Converts:
- domain: → metadata:
- label: → display_name:
- symptoms: → synonyms:
- severity: → severity_levels:
- Top-level sections → nodes: wrapper
"""

import yaml
from pathlib import Path
from datetime import date


def migrate_old_to_new_format(yaml_path: Path) -> bool:
    """Migrate a knowledge graph from old format to new format."""
    print(f"\nMigrating: {yaml_path.name}")

    with open(yaml_path, 'r') as f:
        data = yaml.safe_load(f)

    # Check if already in new format
    if 'metadata' in data and 'nodes' in data:
        print(f"  Already in new format, skipping")
        return False

    # Extract old domain info
    old_domain = data.get('domain', {})
    domain_slug = old_domain.get('slug', yaml_path.stem)
    domain_name = old_domain.get('name', domain_slug.replace('_', ' ').title())
    domain_desc = old_domain.get('description', f'Knowledge graph for {domain_name}')

    # Create new metadata structure
    new_data = {
        'metadata': {
            'domain': domain_slug,
            'version': '1.0.0',
            'created_at': str(date.today()),
            'description': domain_desc,
            'display_name': domain_name,
            'persona': get_persona_for_domain(domain_slug),
            'is_active': True,
            'parent_domain': None
        },
        'nodes': {},
        'edges': []
    }

    # Migrate problems
    old_problems = data.get('problems', [])
    new_problems = []
    for problem in old_problems:
        new_problem = {
            'id': problem['id'],
            'name': problem['id'],
            'display_name': problem.get('label', problem['id'].replace('_', ' ').title()),
            'synonyms': problem.get('symptoms', problem.get('synonyms', [])),
            'severity_levels': ['mild', 'moderate', 'severe'],
            'description': problem.get('description', '')
        }
        new_problems.append(new_problem)
    new_data['nodes']['problems'] = new_problems
    print(f"  Migrated {len(new_problems)} problems")

    # Migrate attributes
    old_attributes = data.get('attributes', [])
    new_attributes = []
    for attr in old_attributes:
        attr_id = attr['id']
        category = attr_id.split('_')[0] if '_' in attr_id else 'general'
        value = attr['id'].split('_')[-1] if '_' in attr_id else attr_id

        new_attr = {
            'id': attr_id,
            'category': category,
            'value': value,
            'data_type': 'single_choice',
            'elicitation_priority': 3,
            'is_global': any(kw in attr_id for kw in ['age', 'gender', 'diet', 'pregnancy', 'medical', 'allergy'])
        }
        new_attributes.append(new_attr)
    new_data['nodes']['attributes'] = new_attributes
    print(f"  Migrated {len(new_attributes)} attributes")

    # Migrate ingredients
    old_ingredients = data.get('ingredients', [])
    new_ingredients = []
    for ing in old_ingredients:
        # Extract dose levels
        typical_dose = ing.get('typical_dose', '')
        import re
        doses = re.findall(r'\d+(?:-\d+)?(?:mg|mcg|IU|g|ml)', typical_dose)
        strength_levels = doses[:3] if doses else ing.get('forms', ['standard'])[:3]
        if not strength_levels:
            strength_levels = ['standard']

        new_ing = {
            'id': ing['id'],
            'name': ing['id'],
            'display_name': ing.get('label', ing['id'].replace('_', ' ').title()),
            'function': ing.get('description', '').split('.')[0].lower().replace(' ', '_')[:50] if ing.get('description') else 'general_support',
            'category': ing.get('category', 'supplement'),
            'strength_levels': strength_levels
        }
        new_ingredients.append(new_ing)
    new_data['nodes']['ingredients'] = new_ingredients
    print(f"  Migrated {len(new_ingredients)} ingredients")

    # Migrate constraints
    old_constraints = data.get('constraints', [])
    new_constraints = []
    for constraint in old_constraints:
        new_constraint = {
            'id': constraint['id'],
            'type': constraint.get('type', 'medical'),
            'value': constraint.get('value', constraint['id'].replace('_', ' ')),
            'severity': constraint.get('severity', 'moderate')
        }
        new_constraints.append(new_constraint)
    new_data['nodes']['constraints'] = new_constraints
    print(f"  Migrated {len(new_constraints)} constraints")

    # Add empty sections
    new_data['nodes']['questions'] = []
    new_data['nodes']['products'] = []
    new_data['nodes']['domains'] = []
    new_data['nodes']['subdomains'] = []

    # Migrate edges
    old_edges = data.get('edges', [])
    new_edges = []
    for edge in old_edges:
        # Handle edges that reference multiple targets
        from_node = edge.get('from', '')
        to_nodes = edge.get('to', [])
        if not isinstance(to_nodes, list):
            to_nodes = [to_nodes]

        for to_node in to_nodes:
            new_edge = {
                'source': from_node,
                'target': to_node,
                'relation': edge.get('relationship', 'RELATED_TO'),
                'properties': {
                    k: v for k, v in edge.items()
                    if k not in ['from', 'to', 'relationship']
                }
            }
            new_edges.append(new_edge)
    new_data['edges'] = new_edges
    print(f"  Migrated {len(new_edges)} edges")

    # Write new format
    with open(yaml_path, 'w') as f:
        yaml.dump(new_data, f, default_flow_style=False, sort_keys=False, width=120, allow_unicode=True)

    print(f"  ✓ Migrated {yaml_path.name}")
    return True


def get_persona_for_domain(domain_slug):
    """Get persona text for domain."""
    personas = {
        'healthy_aging_longevity': 'You are a longevity and healthy aging specialist who helps users find science-backed nutraceutical supplements for cellular health, anti-aging, and vitality. You focus on NAD+ boosters, antioxidants, senolytics, and longevity nutrients.',
        'hormonal_balance': 'You are a hormonal health specialist who helps users find science-backed nutraceutical supplements for hormone balance, PCOS, PMS, menopause, and reproductive health. You focus on adaptogens, hormone-modulating herbs, and micronutrients.',
        'sexual_wellness_vitality': 'You are a sexual wellness and vitality specialist who helps users find science-backed nutraceutical supplements for libido, sexual performance, fertility, and vitality. You focus on circulation enhancers, hormone supporters, and energy boosters.',
    }
    return personas.get(domain_slug, f'You are a {domain_slug.replace("_", " ")} specialist.')


def main():
    """Main migration function."""
    print("="*70)
    print("Knowledge Graph Format Migration")
    print("="*70)
    print("\nConverting old-format graphs to new format...\n")

    graphs_dir = Path(__file__).parent.parent / "app" / "knowledge" / "graphs"

    # Files that need migration (old format)
    old_format_files = [
        "healthy_aging_longevity.yaml",
        "hormonal_balance.yaml",
        "sexual_wellness_vitality.yaml",
    ]

    for filename in old_format_files:
        yaml_path = graphs_dir / filename
        if yaml_path.exists():
            try:
                migrate_old_to_new_format(yaml_path)
            except Exception as e:
                print(f"  ✗ Error migrating {filename}: {e}")
                import traceback
                traceback.print_exc()
        else:
            print(f"  ✗ Not found: {yaml_path}")

    print("\n" + "="*70)
    print("Migration complete!")
    print("="*70)


if __name__ == "__main__":
    main()
