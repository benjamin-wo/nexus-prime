/**
 * Nexus Prime - Capability Manifests Data
 * Sourced directly from capabilities/manifests/*.yaml
 */
const MANIFESTS_DATA = [
  {
    id: "routes",
    title: "Transit & Route Engine",
    description: "Plan trips, transit and driving routes, and answer ETA questions with a complete live picture: journey steps with actual bus line numbers, live next-departure minutes from the exact stop, total time, and a map link. Ask like 'when is my next bus from Tampines?', 'route from Raffles Place to Changi Airport', or 'how long is the drive to KL'.",
    side_effect: "read",
    cost_hint: "medium",
    tags: ["transit", "commute", "bus", "mrt", "travel"],
    managers: ["life", "travel"],
    preconditions: ["Route provider configured (optional for offline fallback)"],
    input_schema: {
      type: "object",
      properties: {
        origin: { type: "string", description: "Starting place (optional; defaults from profile/context)" },
        destination: { type: "string", description: "Destination place" },
        mode: { type: "string", description: "transit, driving, walking, or bicycling" }
      },
      required: []
    },
    output_schema: {
      type: "object",
      properties: {
        route: { type: "object", description: "Origin, destination, ETA in minutes, distance, steps" }
      },
      required: ["route"]
    },
    sample_queries: [
      "When is my next bus 961 from Tampines?",
      "How to get to Marina Bay Sands from Orchard MRT?",
      "How long is the drive to Changi Airport?"
    ]
  },
  {
    id: "expenses",
    title: "Autonomous Expense Tracker",
    description: "Record, categorize, and summarize personal expenses. Ingest receipts and bank notification emails. Ask like 'log $14.50 lunch at Amoy Hawker Centre', 'how much did I spend on groceries this month?', or 'list all expenses from last week'.",
    side_effect: "spend",
    cost_hint: "low",
    tags: ["finance", "money", "budget", "spend", "receipt"],
    managers: ["finance", "life"],
    preconditions: ["Database connected", "Fernet vault unlocked"],
    input_schema: {
      type: "object",
      properties: {
        amount: { type: "number", description: "Amount spent in account currency" },
        currency: { type: "string", description: "3-letter currency code (defaults to SGD/USD)" },
        category: { type: "string", description: "food, transport, groceries, bills, shopping, leisure" },
        merchant: { type: "string", description: "Vendor or store name" },
        date: { type: "string", description: "ISO timestamp or human relative date" }
      },
      required: ["amount"]
    },
    output_schema: {
      type: "object",
      properties: {
        transaction_id: { type: "string", description: "Unique transaction identifier" },
        status: { type: "string", description: "confirmed, pending_clarification, or duplicate" }
      },
      required: ["transaction_id", "status"]
    },
    sample_queries: [
      "Log $45 lunch with client at Odette",
      "Where did all my money go this month?",
      "How much did I spend on Grab rides in July?"
    ]
  },
  {
    id: "email",
    title: "Gmail Ingestion & Presets",
    description: "Read, search, summarize, and draft emails from connected Gmail accounts with two-layer deduplication. Ingest bank transaction alerts, flight receipts, and important updates. Ask like 'check unread emails from my bank', 'search for flight booking confirmation', or 'draft a reply to Sarah'.",
    side_effect: "write",
    cost_hint: "medium",
    tags: ["email", "gmail", "inbox", "search", "communication"],
    managers: ["communication", "finance"],
    preconditions: ["Google OAuth2 credentials in Vault", "Gmail API enabled"],
    input_schema: {
      type: "object",
      properties: {
        query: { type: "string", description: "Search query or sender filter" },
        max_results: { type: "integer", description: "Number of emails to fetch (default 5)" },
        action: { type: "string", enum: ["search", "read", "draft", "tag"] }
      },
      required: ["action"]
    },
    output_schema: {
      type: "object",
      properties: {
        messages: { type: "array", description: "List of email headers and extracted snippets" }
      },
      required: ["messages"]
    },
    sample_queries: [
      "Check unread bank alert emails",
      "Search for Singapore Airlines flight confirmation",
      "Draft a reply confirming meeting for 3pm tomorrow"
    ]
  },
  {
    id: "recipes",
    title: "Smart Recipe & Pantry Engine",
    description: "Search recipes by available ingredients, dietary restrictions, prep time, and cuisine. Generate tailored grocery ingredient shopping lists. Ask like 'what can I cook with chicken breast, broccoli and soy sauce?', 'find a 20-minute vegetarian pasta recipe', or 'grocery list for butter chicken'.",
    side_effect: "read",
    cost_hint: "low",
    tags: ["cooking", "food", "ingredients", "grocery", "meals"],
    managers: ["lifestyle", "cooking"],
    preconditions: [],
    input_schema: {
      type: "object",
      properties: {
        ingredients: { type: "array", items: { type: "string" }, description: "Available ingredients" },
        dietary: { type: "string", description: "vegan, vegetarian, gluten-free, keto, halal" },
        max_time_mins: { type: "integer", description: "Maximum cooking time in minutes" }
      },
      required: []
    },
    output_schema: {
      type: "object",
      properties: {
        recipe_name: { type: "string" },
        prep_time: { type: "string" },
        ingredients: { type: "array" },
        instructions: { type: "array" }
      },
      required: ["recipe_name", "ingredients", "instructions"]
    },
    sample_queries: [
      "Find a 15-minute healthy dinner with salmon",
      "What can I cook with eggs, tofu, and scallions?",
      "Generate grocery checklist for homemade ramen"
    ]
  },
  {
    id: "reminders",
    title: "Proactive Reminders & Gated Delivery",
    description: "Set, list, modify, and delete time-based reminders and recurring alerts with dynamic IANA timezone auto-recalculation and quiet-hours ambient delivery gating. Ask like 'remind me to call Mom tomorrow at 6pm', 'remind me in 30 mins to take the laundry out', or 'what reminders do I have today?'.",
    side_effect: "write",
    cost_hint: "low",
    tags: ["reminders", "tasks", "alerts", "schedule", "todo"],
    managers: ["life", "productivity"],
    preconditions: ["Scheduler engine running", "Timezone resolved"],
    input_schema: {
      type: "object",
      properties: {
        text: { type: "string", description: "Reminder description" },
        target_time: { type: "string", description: "Natural language time or ISO format" },
        priority: { type: "string", enum: ["urgent", "normal", "low"] }
      },
      required: ["text", "target_time"]
    },
    output_schema: {
      type: "object",
      properties: {
        reminder_id: { type: "string" },
        scheduled_local_time: { type: "string" },
        timezone: { type: "string" }
      },
      required: ["reminder_id", "scheduled_local_time"]
    },
    sample_queries: [
      "Remind me to submit monthly expense report at 5pm",
      "Remind me in 45 minutes to take bread out of oven",
      "List all active reminders for this weekend"
    ]
  },
  {
    id: "code_exec",
    title: "Isolated Sandboxed Code Runner",
    description: "Execute Python code in an isolated, egress-restricted, timeout-bounded sandbox (E2B in production / process-isolated container locally). Secret vault is unreachable; egress restricted to strict allowlist. Ideal for data analysis, mortgage calculations, chart generation, and data transformation.",
    side_effect: "read",
    cost_hint: "high",
    tags: ["code", "python", "data", "compute", "analysis", "sandbox"],
    managers: ["engineering", "finance"],
    preconditions: ["Code sandbox provider healthy", "Import allowlist checked"],
    input_schema: {
      type: "object",
      properties: {
        code: { type: "string", description: "Python code snippet to execute" },
        timeout_seconds: { type: "integer", description: "Max execution time (capped at 15s)" }
      },
      required: ["code"]
    },
    output_schema: {
      type: "object",
      properties: {
        stdout: { type: "string" },
        result: { type: "any" },
        execution_time_ms: { type: "number" }
      },
      required: ["stdout"]
    },
    sample_queries: [
      "Run Python to calculate compound interest on $10k over 10 years at 8%",
      "Write a script to aggregate my monthly grocery expenses and find variance",
      "Generate monthly loan amortization schedule for $500,000 at 3.5%"
    ]
  },
  {
    id: "general",
    title: "General Knowledge & Reasoning",
    description: "General question answering, language translation, creative writing, conceptual explanations, and advice that do not require external private integrations or specialized tool side-effects.",
    side_effect: "read",
    cost_hint: "low",
    tags: ["general", "qa", "chat", "writing", "facts"],
    managers: ["general"],
    preconditions: [],
    input_schema: {
      type: "object",
      properties: {
        query: { type: "string", description: "User question or prompt" }
      },
      required: ["query"]
    },
    output_schema: {
      type: "object",
      properties: {
        answer: { type: "string" }
      },
      required: ["answer"]
    },
    sample_queries: [
      "Why is the sky blue during sunset?",
      "Translate 'Where is the nearest train station?' into Japanese",
      "Explain the difference between AsyncIO and Multiprocessing in Python"
    ]
  }
];

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { MANIFESTS_DATA };
}
