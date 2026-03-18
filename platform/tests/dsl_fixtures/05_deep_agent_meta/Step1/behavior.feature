Feature: Deep Agent with Meta Operations
  Advanced agent that can discover and orchestrate other workflows

  Background:
    Given the workflow is triggered by Telegram message
    And the user has at least one LLM credential configured
    And the platform has existing workflows

  Scenario: Agent identifies itself
    When the agent needs context about its environment
    Then it uses whoami tool
    And receives its workflow ID and node ID

  Scenario: Discover existing workflow
    When the user asks "find a workflow that can process images"
    Then the agent uses workflow_discover tool
    And receives matching workflow suggestions

  Scenario: Check system health before spawning
    When the agent decides to spawn a child workflow
    Then it first uses system_health tool
    And verifies the platform is healthy
    And proceeds only if health check passes

  Scenario: Spawn and await child workflow
    Given a suitable workflow was discovered
    And system health is good
    When the agent spawns the child workflow
    Then it uses spawn_and_await tool
    And waits for the child to complete
    And receives the child's result

  Scenario: Make platform API call
    When the agent needs to interact with platform resources
    Then it uses platform_api tool
    And makes authenticated requests
