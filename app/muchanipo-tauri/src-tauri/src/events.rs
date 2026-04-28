use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BackendEvent {
    pub event: String,
    #[serde(flatten)]
    pub fields: Map<String, Value>,
}

impl BackendEvent {
    pub fn from_json_line(line: &str) -> Result<Self, serde_json::Error> {
        serde_json::from_str(line)
    }

    pub fn error(message: impl Into<String>) -> Self {
        let mut fields = Map::new();
        fields.insert("message".to_string(), Value::String(message.into()));

        Self {
            event: "error".to_string(),
            fields,
        }
    }

    pub fn warning(message: impl Into<String>) -> Self {
        let mut fields = Map::new();
        fields.insert("message".to_string(), Value::String(message.into()));

        Self {
            event: "warning".to_string(),
            fields,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BackendAction {
    #[serde(flatten)]
    pub fields: Map<String, Value>,
}

impl BackendAction {
    pub fn into_json_line(mut self) -> Result<String, serde_json::Error> {
        if !self.fields.contains_key("action") {
            if let Some(kind) = self.fields.remove("type") {
                self.fields
                    .insert("action".to_string(), normalize_action(kind));
            }
        }

        serde_json::to_string(&self.fields).map(|mut line| {
            line.push('\n');
            line
        })
    }
}

fn normalize_action(kind: Value) -> Value {
    match kind.as_str() {
        Some("cancel") => Value::String("abort".to_string()),
        Some(other) => Value::String(other.to_string()),
        None => kind,
    }
}
