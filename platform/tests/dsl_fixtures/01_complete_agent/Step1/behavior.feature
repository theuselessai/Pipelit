Feature: Complete Agent
  An agent that can perform calculations, execute code, and search the web

  Background:
    Given the workflow is triggered manually
    And the user has at least one LLM credential configured

  Scenario: User asks for a calculation
    When the user asks "what is 25 * 4?"
    Then the agent should use the calculator tool
    And return the result "100"

  Scenario: User asks to run code
    When the user asks "run print('hello world')"
    Then the agent should use the code execution tool
    And return the output "hello world"

  Scenario: User asks a factual question
    When the user asks "what is the capital of France?"
    Then the agent should use the web search tool
    And return a factual answer

  Scenario: Response is formatted
    When the agent completes its response
    Then the format_output step processes the result
