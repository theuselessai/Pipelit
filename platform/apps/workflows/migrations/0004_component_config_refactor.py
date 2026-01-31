"""Refactor ComponentConfig into multi-table inheritance hierarchy.

- Rename ComponentConfig → BaseComponentConfig
- Create child tables: ModelComponentConfig, AIComponentConfig, CodeComponentConfig,
  ToolComponentConfig, OtherComponentConfig
- Rename component types: chat_model→ai_model, react_agent→simple_agent,
  plan_and_execute→planner_agent
- Add edge_label to WorkflowEdge
- Migrate existing data to child tables
"""

import django.db.models.deletion
from django.db import migrations, models

# Old → new component type mapping
TYPE_RENAMES = {
    "chat_model": "ai_model",
    "react_agent": "simple_agent",
    "plan_and_execute": "planner_agent",
}

# Component type → child table name
TYPE_TO_CHILD = {
    "ai_model": "workflows_modelcomponentconfig",
    "simple_agent": "workflows_aicomponentconfig",
    "planner_agent": "workflows_aicomponentconfig",
    "categorizer": "workflows_aicomponentconfig",
    "router": "workflows_aicomponentconfig",
    "code": "workflows_codecomponentconfig",
    "loop": "workflows_codecomponentconfig",
    "filter": "workflows_codecomponentconfig",
    "transform": "workflows_codecomponentconfig",
    "sort": "workflows_codecomponentconfig",
    "limit": "workflows_codecomponentconfig",
    "merge": "workflows_codecomponentconfig",
    "wait": "workflows_codecomponentconfig",
    "parallel": "workflows_codecomponentconfig",
    "error_handler": "workflows_codecomponentconfig",
    "tool_node": "workflows_toolcomponentconfig",
    "http_request": "workflows_toolcomponentconfig",
    "human_confirmation": "workflows_othercomponentconfig",
    "aggregator": "workflows_othercomponentconfig",
    "workflow": "workflows_othercomponentconfig",
    "output_parser": "workflows_othercomponentconfig",
}


def migrate_data_forward(apps, schema_editor):
    """Migrate data from old ComponentConfig to new hierarchy."""
    db = schema_editor.connection.alias
    cursor = schema_editor.connection.cursor()

    # 1. Rename component types on both ComponentConfig and WorkflowNode
    for old_type, new_type in TYPE_RENAMES.items():
        cursor.execute(
            "UPDATE workflows_componentconfig SET component_type = %s WHERE component_type = %s",
            [new_type, old_type],
        )
        cursor.execute(
            "UPDATE workflows_workflownode SET component_type = %s WHERE component_type = %s",
            [new_type, old_type],
        )

    # 2. Copy all rows from componentconfig to basecomponentconfig (same schema for base fields)
    cursor.execute("""
        INSERT INTO workflows_basecomponentconfig (id, component_type, extra_config, updated_at)
        SELECT id, component_type, extra_config, updated_at
        FROM workflows_componentconfig
    """)

    # 3. Create child table rows based on component_type
    # ModelComponentConfig (ai_model) — has llm_model_id, llm_credential_id, system_prompt
    cursor.execute("""
        INSERT INTO workflows_modelcomponentconfig (basecomponentconfig_ptr_id, system_prompt, llm_model_id, llm_credential_id)
        SELECT id, system_prompt, llm_model_id, llm_credential_id
        FROM workflows_componentconfig
        WHERE component_type = 'ai_model'
    """)

    # AIComponentConfig (simple_agent, planner_agent, categorizer, router) — has system_prompt
    cursor.execute("""
        INSERT INTO workflows_aicomponentconfig (basecomponentconfig_ptr_id, system_prompt)
        SELECT id, system_prompt
        FROM workflows_componentconfig
        WHERE component_type IN ('simple_agent', 'planner_agent', 'categorizer', 'router')
    """)

    # CodeComponentConfig — code_language, code_snippet default to empty
    cursor.execute("""
        INSERT INTO workflows_codecomponentconfig (basecomponentconfig_ptr_id, code_language, code_snippet)
        SELECT id, 'python', ''
        FROM workflows_componentconfig
        WHERE component_type IN ('code', 'loop', 'filter', 'transform', 'sort', 'limit', 'merge', 'wait', 'parallel', 'error_handler')
    """)

    # ToolComponentConfig
    cursor.execute("""
        INSERT INTO workflows_toolcomponentconfig (basecomponentconfig_ptr_id)
        SELECT id
        FROM workflows_componentconfig
        WHERE component_type IN ('tool_node', 'http_request')
    """)

    # OtherComponentConfig
    cursor.execute("""
        INSERT INTO workflows_othercomponentconfig (basecomponentconfig_ptr_id)
        SELECT id
        FROM workflows_componentconfig
        WHERE component_type IN ('human_confirmation', 'aggregator', 'workflow', 'output_parser')
    """)

    # 4. For AI nodes that had llm_model_id + llm_credential_id, create ai_model nodes + llm edges
    cursor.execute("""
        SELECT cc.id, cc.llm_model_id, cc.llm_credential_id, wn.workflow_id, wn.node_id, wn.position_x, wn.position_y
        FROM workflows_componentconfig cc
        JOIN workflows_workflownode wn ON wn.component_config_id = cc.id
        WHERE cc.component_type IN ('simple_agent', 'planner_agent', 'categorizer', 'router')
          AND cc.llm_model_id IS NOT NULL
          AND cc.llm_credential_id IS NOT NULL
    """)
    rows = cursor.fetchall()
    for cc_id, llm_model_id, llm_credential_id, workflow_id, node_id, pos_x, pos_y in rows:
        # Create a BaseComponentConfig for the new ai_model node
        cursor.execute("""
            INSERT INTO workflows_basecomponentconfig (component_type, extra_config, updated_at)
            VALUES ('ai_model', '{}', datetime('now'))
        """)
        new_base_id = cursor.lastrowid

        # Create ModelComponentConfig child
        cursor.execute("""
            INSERT INTO workflows_modelcomponentconfig (basecomponentconfig_ptr_id, system_prompt, llm_model_id, llm_credential_id)
            VALUES (%s, '', %s, %s)
        """, [new_base_id, llm_model_id, llm_credential_id])

        # Create the ai_model WorkflowNode
        new_node_id = f"_llm_for_{node_id}"
        cursor.execute("""
            INSERT INTO workflows_workflownode
                (workflow_id, node_id, component_type, component_config_id,
                 is_entry_point, interrupt_before, interrupt_after,
                 position_x, position_y, updated_at)
            VALUES (%s, %s, 'ai_model', %s, 0, 0, 0, %s, %s, datetime('now'))
        """, [workflow_id, new_node_id, new_base_id, pos_x + 200, pos_y - 100])

        # Create llm edge: AI node → ai_model node
        cursor.execute("""
            INSERT INTO workflows_workflowedge
                (workflow_id, source_node_id, target_node_id, edge_type, edge_label, priority, condition_mapping)
            VALUES (%s, %s, %s, 'direct', 'llm', 0, NULL)
        """, [workflow_id, node_id, new_node_id])

    # 5. Update WorkflowNode FK to point to basecomponentconfig
    # (the AlterField migration op handles the schema change;
    #  data is already correct since IDs match)

    # 6. Reset SQLite autoincrement sequence for basecomponentconfig
    cursor.execute("""
        UPDATE sqlite_sequence SET seq = (SELECT MAX(id) FROM workflows_basecomponentconfig)
        WHERE name = 'workflows_basecomponentconfig'
    """)


def migrate_data_backward(apps, schema_editor):
    """Reverse: move data back to flat ComponentConfig."""
    cursor = schema_editor.connection.cursor()

    # Recreate rows in componentconfig from basecomponentconfig + child tables
    cursor.execute("""
        INSERT INTO workflows_componentconfig (id, component_type, extra_config, updated_at, system_prompt, llm_model_id, llm_credential_id)
        SELECT
            b.id,
            b.component_type,
            b.extra_config,
            b.updated_at,
            COALESCE(m.system_prompt, a.system_prompt, ''),
            m.llm_model_id,
            m.llm_credential_id
        FROM workflows_basecomponentconfig b
        LEFT JOIN workflows_modelcomponentconfig m ON m.basecomponentconfig_ptr_id = b.id
        LEFT JOIN workflows_aicomponentconfig a ON a.basecomponentconfig_ptr_id = b.id
    """)

    # Rename types back
    for old_type, new_type in TYPE_RENAMES.items():
        cursor.execute(
            "UPDATE workflows_componentconfig SET component_type = %s WHERE component_type = %s",
            [old_type, new_type],
        )
        cursor.execute(
            "UPDATE workflows_workflownode SET component_type = %s WHERE component_type = %s",
            [old_type, new_type],
        )

    # Delete auto-created ai_model nodes
    cursor.execute("DELETE FROM workflows_workflownode WHERE node_id LIKE '\\_llm\\_for\\_%' ESCAPE '\\'")
    cursor.execute("DELETE FROM workflows_workflowedge WHERE edge_label = 'llm'")


NEW_CHOICES = [
    ('categorizer', 'Categorizer'), ('router', 'Router'), ('ai_model', 'AI Model'),
    ('simple_agent', 'Simple Agent'), ('planner_agent', 'Planner Agent'),
    ('tool_node', 'Tool Node'), ('aggregator', 'Aggregator'),
    ('human_confirmation', 'Human Confirmation'), ('parallel', 'Parallel'),
    ('workflow', 'Workflow'), ('code', 'Code'), ('loop', 'Loop'), ('wait', 'Wait'),
    ('merge', 'Merge'), ('filter', 'Filter'), ('transform', 'Transform'),
    ('sort', 'Sort'), ('limit', 'Limit'), ('http_request', 'HTTP Request'),
    ('error_handler', 'Error Handler'), ('output_parser', 'Output Parser'),
]


class Migration(migrations.Migration):

    dependencies = [
        ('credentials', '0001_initial'),
        ('workflows', '0003_componentconfig_llm_credential_and_more'),
    ]

    operations = [
        # 1. Create BaseComponentConfig table
        migrations.CreateModel(
            name='BaseComponentConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('component_type', models.CharField(choices=NEW_CHOICES, max_length=30)),
                ('extra_config', models.JSONField(default=dict, help_text='temperature, max_tokens, categories, etc.')),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
        ),

        # 2. Create child tables
        migrations.CreateModel(
            name='ModelComponentConfig',
            fields=[
                ('basecomponentconfig_ptr', models.OneToOneField(auto_created=True, on_delete=django.db.models.deletion.CASCADE, parent_link=True, primary_key=True, serialize=False, to='workflows.basecomponentconfig')),
                ('system_prompt', models.TextField(blank=True, default='')),
                ('llm_credential', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='credentials.llmprovidercredentials')),
                ('llm_model', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='credentials.llmmodel')),
            ],
            bases=('workflows.basecomponentconfig',),
        ),
        migrations.CreateModel(
            name='AIComponentConfig',
            fields=[
                ('basecomponentconfig_ptr', models.OneToOneField(auto_created=True, on_delete=django.db.models.deletion.CASCADE, parent_link=True, primary_key=True, serialize=False, to='workflows.basecomponentconfig')),
                ('system_prompt', models.TextField(blank=True, default='')),
            ],
            bases=('workflows.basecomponentconfig',),
        ),
        migrations.CreateModel(
            name='CodeComponentConfig',
            fields=[
                ('basecomponentconfig_ptr', models.OneToOneField(auto_created=True, on_delete=django.db.models.deletion.CASCADE, parent_link=True, primary_key=True, serialize=False, to='workflows.basecomponentconfig')),
                ('code_language', models.CharField(blank=True, default='python', max_length=20)),
                ('code_snippet', models.TextField(blank=True, default='')),
            ],
            bases=('workflows.basecomponentconfig',),
        ),
        migrations.CreateModel(
            name='ToolComponentConfig',
            fields=[
                ('basecomponentconfig_ptr', models.OneToOneField(auto_created=True, on_delete=django.db.models.deletion.CASCADE, parent_link=True, primary_key=True, serialize=False, to='workflows.basecomponentconfig')),
            ],
            bases=('workflows.basecomponentconfig',),
        ),
        migrations.CreateModel(
            name='OtherComponentConfig',
            fields=[
                ('basecomponentconfig_ptr', models.OneToOneField(auto_created=True, on_delete=django.db.models.deletion.CASCADE, parent_link=True, primary_key=True, serialize=False, to='workflows.basecomponentconfig')),
            ],
            bases=('workflows.basecomponentconfig',),
        ),

        # 3. Add edge_label to WorkflowEdge
        migrations.AddField(
            model_name='workflowedge',
            name='edge_label',
            field=models.CharField(blank=True, choices=[('', 'Control Flow'), ('llm', 'LLM'), ('tool', 'Tool'), ('memory', 'Memory'), ('output_parser', 'Output Parser')], default='', max_length=20),
        ),

        # 4. Update component_type choices on WorkflowNode
        migrations.AlterField(
            model_name='workflownode',
            name='component_type',
            field=models.CharField(choices=NEW_CHOICES, max_length=30),
        ),

        # 5. Migrate data: copy from ComponentConfig to new tables, rename types
        migrations.RunPython(migrate_data_forward, migrate_data_backward),

        # 6. Point WorkflowNode FK to BaseComponentConfig
        migrations.AlterField(
            model_name='workflownode',
            name='component_config',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='nodes', to='workflows.basecomponentconfig'),
        ),

        # 7. Drop old ComponentConfig table
        migrations.DeleteModel(
            name='ComponentConfig',
        ),
    ]
