Feature: Memory and Subworkflow
  Load user context, access memory, and delegate to child workflow

  Background:
    Given the workflow is triggered by another workflow
    And the child workflow "message-processor" exists

  Scenario: Identify the user
    When the workflow receives a trigger with user_id
    Then identify_user extracts the user identity
    And loads user preferences and context

  Scenario: Read past memories
    Given the user has been identified
    When read_memory executes
    Then it retrieves relevant facts and episodes
    And makes them available to downstream nodes

  Scenario: Delegate to child workflow
    Given user context and memories are loaded
    When call_processor executes
    Then it invokes the "message-processor" workflow
    And passes user context and memories as input
    And waits for the child workflow result

  Scenario: Store new memories
    Given the child workflow returned a result
    When write_memory executes
    Then it stores new facts or episodes
    And the memories are persisted for future use
