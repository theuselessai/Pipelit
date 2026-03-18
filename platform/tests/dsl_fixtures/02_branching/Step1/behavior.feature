Feature: Branching Flow
  Categorize incoming messages and route to appropriate handlers

  Background:
    Given the workflow is triggered by chat message
    And the user has at least one LLM credential configured

  Scenario: Urgent message requires human approval
    When the user sends "URGENT: server is down!"
    Then the categorizer identifies it as "urgent"
    And the message is routed to urgent_handler
    And the workflow pauses for human confirmation

  Scenario: Question gets rate-limited
    When the user sends "How do I reset my password?"
    Then the categorizer identifies it as "question"
    And the message is routed to question_handler
    And the workflow waits 2 seconds before continuing

  Scenario: Feedback is acknowledged
    When the user sends "Great service, thanks!"
    Then the categorizer identifies it as "feedback"
    And the message is routed to feedback_handler
    And an acknowledgment is returned

  Scenario: Unknown category uses default
    When the user sends "xyz123"
    Then the categorizer output doesn't match any rule
    And the message is routed to feedback_handler (default)
