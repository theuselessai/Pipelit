Feature: Error Handling and Routing
  Fetch external data and handle success/error cases appropriately

  Background:
    Given the workflow is triggered manually
    And the user has at least one LLM credential configured

  Scenario: Successful data fetch
    When fetch_data returns status 200
    Then the response is routed to process_success
    And the data is transformed for output

  Scenario: Client error creates task
    When fetch_data returns status 400
    Then the response is routed to handle_error
    And the agent analyzes the error
    And creates an epic for tracking
    And creates a task for follow-up

  Scenario: Server error creates task
    When fetch_data returns status 500
    Then the response is routed to handle_error
    And the agent creates a task for investigation

  Scenario: Unknown status schedules retry
    When fetch_data returns status 302
    Then the response is routed to handle_unknown (default)
    And the agent schedules a retry
    And the retry is configured appropriately

  Scenario: Timeout handling
    When fetch_data times out
    Then it is treated as an error
    And routed to handle_error
