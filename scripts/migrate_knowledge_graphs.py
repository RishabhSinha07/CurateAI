#!/usr/bin/env python3
"""
Migration script to convert knowledge graphs from old schema to new schema.

Old Schema:
- domain: { slug, name, description }
- problems: [...]
- attributes: [...]
- ingredients: [...]
- constraints: [...]
- edges: [{ from, to, relationship }]

New Schema:
- metadata: { domain, version, created_at, description, display_name, persona, is_active, parent_domain }
- nodes: { problems: [...], attributes: [...], ingredients: [...], constraints: [...] }
- edges: [{ source, target, relation }]
"""

import yaml
from pathlib import Path
from datetime import date
from typing import Dict, Any, List


# Domain-specific personas for the metadata
DOMAIN_PERSONAS = {
    "sexual_wellness_vitality": """You are a sexual wellness and vitality specialist who helps users find science-backed supplements for libido, performance, fertility, and overall sexual health. You focus on adaptogens, circulation enhancers, hormone support, and energy boosters that promote healthy sexual function across all life stages. You consider age, gender, lifestyle factors, and specific concerns to provide personalized, respectful, and evidence-based recommendations.""",

    "hormonal_balance": """You are a hormonal health specialist who helps users find supplements to support hormone balance across life stages. You focus on PCOS, PMS, menopause, thyroid health, and fertility support through ingredients like inositol, vitex, ashwagandha, and key vitamins/minerals. You consider menstrual cycle regularity, age, symptoms, and medical history to provide safe, personalized recommendations.""",

    "healthy_aging_longevity": """You are a longevity and anti-aging specialist who helps users find science-backed supplements for cellular health, healthy aging, and vitality. You focus on NAD+ precursors, antioxidants, mitochondrial support, and senolytics that promote graceful aging and disease prevention. You consider age, health optimization goals, and chronic conditions to provide evidence-based recommendations for healthspan and lifespan extension.""",

    "joint_bone_mobility": """You are a musculoskeletal health specialist who helps users find supplements for bone density, joint comfort, and mobility. You focus on calcium, vitamin D3/K2, collagen, glucosamine, and anti-inflammatory nutrients that support healthy bones, cartilage, and connective tissue. You consider age, activity level, existing conditions (osteoporosis, arthritis), and mobility goals to provide personalized recommendations.""",

    "brain_focus_memory": """You are a cognitive health specialist who helps users find supplements for brain function, focus, and memory. You focus on omega-3 DHA, nootropics, B vitamins, and neuroprotective compounds that support mental clarity, concentration, and cognitive longevity. You consider age, cognitive goals (studying, work performance, aging), and lifestyle factors to provide evidence-based recommendations.""",

    "sleep_stress_mental_calm": """You are a sleep and stress management specialist who helps users find supplements for better sleep quality, stress reduction, and mental calm. You focus on melatonin, magnesium, adaptogens, and calming herbs that promote relaxation, healthy sleep patterns, and stress resilience. You consider sleep issues, stress levels, lifestyle factors, and existing medications to provide safe, effective recommendations.""",

    "weight_management_metabolism": """You are a metabolic health specialist who helps users find supplements for healthy weight management and metabolic function. You focus on fiber, green tea extract, metabolism boosters, and appetite control ingredients that support fat loss, insulin sensitivity, and metabolic health. You consider weight goals, activity level, dietary habits, and metabolic issues to provide personalized, sustainable recommendations.""",

    "muscle_strength_recovery": """You are a sports nutrition and muscle health specialist who helps users find supplements for muscle building, strength gains, and recovery. You focus on protein, creatine, BCAAs, and recovery-enhancing nutrients that support muscle protein synthesis, strength, and post-workout recovery. You consider training goals, activity level, dietary preferences (vegan/omnivore), and recovery needs to provide evidence-based recommendations.""",
}


def convert_domain_to_metadata(old_domain: Dict[str, Any], domain_slug: str) -> Dict[str, Any]:
    """Convert old domain section to new metadata format."""
    display_name = old_domain.get('name', domain_slug.replace('_', ' ').title())

    return {
        'domain': domain_slug,
        'version': '1.0.0',
        'created_at': str(date.today()),
        'description': old_domain.get('description', f'Knowledge graph for {display_name}'),
        'display_name': display_name,
        'persona': DOMAIN_PERSONAS.get(domain_slug, f'You are a {display_name} specialist.'),
        'is_active': True,
        'parent_domain': None
    }


def convert_problems_to_nodes(problems: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert problem list to new node format with synonyms."""
    node_problems = []

    for problem in problems:
        problem_id = problem.get('id')
        label = problem.get('label', problem_id.replace('_', ' ').title())

        # Extract keywords from description and symptoms to create synonyms
        synonyms = []
        description = problem.get('description', '').lower()
        symptoms = problem.get('symptoms', [])

        # Add label variations as synonyms
        synonyms.append(label.lower())
        synonyms.append(problem_id.replace('_', ' '))

        # Add symptoms as potential synonyms
        for symptom in symptoms[:5]:  # Limit to 5 most relevant
            if isinstance(symptom, str):
                synonyms.append(symptom.lower())

        # Remove duplicates and the ID itself
        synonyms = list(dict.fromkeys(synonyms))  # Remove duplicates while preserving order
        synonyms = [s for s in synonyms if s != problem_id]

        node_problems.append({
            'id': problem_id,
            'name': problem_id,
            'display_name': label,
            'synonyms': synonyms[:8],  # Limit to 8 most relevant synonyms
            'severity_levels': ['mild', 'moderate', 'severe'],
            'description': problem.get('description', ''),
        })

    return node_problems


def convert_attributes_to_nodes(attributes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert attribute list to new node format."""
    node_attributes = []

    for attr in attributes:
        attr_id = attr.get('id')
        label = attr.get('label', attr_id.replace('_', ' ').title())
        attr_type = attr.get('type', 'categorical')

        node_attr = {
            'id': attr_id,
            'name': attr_id,
            'display_name': label,
            'attribute_type': attr_type,
            'description': f'{label} - used for personalized recommendations'
        }

        # Add values if categorical or multi_select
        if attr_type in ['categorical', 'multi_select']:
            node_attr['values'] = attr.get('values', [])

        node_attributes.append(node_attr)

    return node_attributes


def convert_ingredients_to_nodes(ingredients: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert ingredient list to new node format."""
    node_ingredients = []

    for ingredient in ingredients:
        ing_id = ingredient.get('id')
        label = ingredient.get('label', ing_id.replace('_', ' ').title())

        node_ingredients.append({
            'id': ing_id,
            'name': ing_id,
            'display_name': label,
            'category': ingredient.get('category', 'supplement'),
            'forms': ingredient.get('forms', []),
            'typical_dose': ingredient.get('typical_dose', 'varies'),
            'description': f'{label} - {ingredient.get("category", "supplement")}'
        })

    return node_ingredients


def convert_constraints_to_nodes(constraints: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert constraint list to new node format."""
    node_constraints = []

    for constraint in constraints:
        const_id = constraint.get('id')
        label = constraint.get('label', const_id.replace('_', ' ').title())

        node_constraints.append({
            'id': const_id,
            'name': const_id,
            'display_name': label,
            'constraint_type': constraint.get('type', 'contraindication'),
            'severity': constraint.get('severity', 'moderate'),
            'applies_to': constraint.get('applies_to', []),
            'description': label
        })

    return node_constraints


def convert_edges(edges: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert edge list from old format to new format."""
    new_edges = []

    for edge in edges:
        # Map old field names to new
        new_edge = {
            'source': edge.get('from'),
            'target': edge.get('to'),
            'relation': edge.get('relationship'),
        }

        # Copy over optional fields if they exist
        optional_fields = ['efficacy', 'mechanism', 'evidence_level', 'onset',
                          'reason', 'severity', 'priority']
        for field in optional_fields:
            if field in edge:
                new_edge[field] = edge[field]

        new_edges.append(new_edge)

    return new_edges


def migrate_graph(yaml_path: Path) -> bool:
    """
    Migrate a single knowledge graph from old schema to new schema.

    Returns:
        True if migration was successful, False otherwise
    """
    print(f"\n{'='*70}")
    print(f"Migrating: {yaml_path.name}")
    print(f"{'='*70}")

    # Read the old YAML
    with open(yaml_path, 'r') as f:
        old_data = yaml.safe_load(f)

    # Check if already in new format
    if 'metadata' in old_data and 'nodes' in old_data:
        print(f"✓ {yaml_path.name} already in new format - skipping")
        return True

    # Extract domain slug from old structure
    domain_slug = old_data.get('domain', {}).get('slug')
    if not domain_slug:
        print(f"✗ {yaml_path.name} missing domain slug - cannot migrate")
        return False

    print(f"Domain slug: {domain_slug}")

    # Build new structure
    new_data = {}

    # 1. Convert metadata
    new_data['metadata'] = convert_domain_to_metadata(
        old_data.get('domain', {}),
        domain_slug
    )
    print(f"✓ Converted metadata")

    # 2. Convert nodes
    nodes = {}

    if 'problems' in old_data:
        nodes['problems'] = convert_problems_to_nodes(old_data['problems'])
        print(f"✓ Converted {len(nodes['problems'])} problems to nodes")

    if 'attributes' in old_data:
        nodes['attributes'] = convert_attributes_to_nodes(old_data['attributes'])
        print(f"✓ Converted {len(nodes['attributes'])} attributes to nodes")

    if 'ingredients' in old_data:
        nodes['ingredients'] = convert_ingredients_to_nodes(old_data['ingredients'])
        print(f"✓ Converted {len(nodes['ingredients'])} ingredients to nodes")

    if 'constraints' in old_data:
        nodes['constraints'] = convert_constraints_to_nodes(old_data['constraints'])
        print(f"✓ Converted {len(nodes['constraints'])} constraints to nodes")

    new_data['nodes'] = nodes

    # 3. Convert edges
    if 'edges' in old_data:
        new_data['edges'] = convert_edges(old_data['edges'])
        print(f"✓ Converted {len(new_data['edges'])} edges")

    # 4. Write back to file
    with open(yaml_path, 'w') as f:
        yaml.dump(new_data, f, default_flow_style=False, sort_keys=False, width=120)

    print(f"✓ Successfully migrated {yaml_path.name}")
    return True


def main():
    """Main migration function."""
    print("\n" + "="*70)
    print("Knowledge Graph Schema Migration")
    print("="*70)
    print("\nThis script will migrate knowledge graphs from old schema to new schema.")
    print("Old graphs will be backed up before migration.\n")

    # Find all YAML files in graphs directory
    graphs_dir = Path(__file__).parent.parent / "app" / "knowledge" / "graphs"

    if not graphs_dir.exists():
        print(f"Error: Graphs directory not found: {graphs_dir}")
        return

    yaml_files = list(graphs_dir.glob("*.yaml"))

    if not yaml_files:
        print(f"No YAML files found in {graphs_dir}")
        return

    print(f"Found {len(yaml_files)} knowledge graph files\n")

    # Create backup directory
    backup_dir = graphs_dir / "backup_pre_migration"
    backup_dir.mkdir(exist_ok=True)

    print(f"Backing up original files to: {backup_dir}\n")

    # Migrate each file
    success_count = 0
    skip_count = 0
    fail_count = 0

    for yaml_file in sorted(yaml_files):
        # Backup original
        backup_path = backup_dir / yaml_file.name
        if not backup_path.exists():  # Only backup if not already backed up
            import shutil
            shutil.copy2(yaml_file, backup_path)

        # Migrate
        try:
            if migrate_graph(yaml_file):
                # Check if it was actually migrated or skipped
                with open(yaml_file, 'r') as f:
                    data = yaml.safe_load(f)
                if 'metadata' in data:
                    if 'nodes' in data:
                        success_count += 1
                    else:
                        skip_count += 1
                else:
                    skip_count += 1
            else:
                fail_count += 1
        except Exception as e:
            print(f"✗ Error migrating {yaml_file.name}: {e}")
            fail_count += 1

    # Summary
    print("\n" + "="*70)
    print("Migration Summary")
    print("="*70)
    print(f"✓ Successfully migrated: {success_count}")
    print(f"⊘ Already in new format (skipped): {skip_count}")
    print(f"✗ Failed to migrate: {fail_count}")
    print(f"\nBackups saved to: {backup_dir}")
    print("\nNext steps:")
    print("1. Verify the migrated graphs are correct")
    print("2. Restart the application to load the new graphs")
    print("3. Test domain routing with: docker compose exec app python -c \"from app.knowledge.graph_loader import get_all_active_domains; print([d['domain'] for d in get_all_active_domains()])\"")
    print("="*70 + "\n")


if __name__ == "__main__":
    main()
