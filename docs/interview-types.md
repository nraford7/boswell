# Interview Types & Angles

Interview Types allow you to configure how Boswell approaches conversations. Each type bundles **content** (questions, research materials) with a **style** (the angle Boswell takes during the interview).

## Interview Angles

Boswell supports five interview angles, each changing how the AI conducts the conversation:

| Angle | Description | Best For |
|-------|-------------|----------|
| **Exploratory** | Boswell learns from the guest about a topic. Probes deeper, follows tangents, surfaces knowledge. | Customer research, domain expertise interviews |
| **Interrogative** | Boswell challenges claims and reasoning. Asks for evidence, surfaces weaknesses, stress-tests ideas. | Expert interviews, due diligence, thesis validation |
| **Imaginative** | Boswell collaborates creatively. Builds on ideas, explores "what if" scenarios, develops thinking. | Ideation sessions, brainstorming, vision development |
| **Documentary** | Boswell captures the guest's story. Lets them lead, minimal steering, preserves their voice. | Oral histories, testimonials, narrative capture |
| **Coaching** | Boswell helps guests think through something themselves. Reflects back, uses Socratic questioning. | Executive coaching, self-reflection, decision support |

### Blending Angles

You can optionally add a **secondary angle** to blend approaches. For example:
- **Exploratory + Documentary**: Learn about a topic while capturing the guest's personal narrative
- **Interrogative + Coaching**: Challenge ideas while helping the guest discover their own insights

## Creating Interview Templates

Templates bundle content and style for reuse across multiple interviews.

### Navigate to Interview Types

1. Go to `/admin/templates` or click "Interview Types" in the navigation
2. Click "New Interview Type"

### Configure the Template

**Template Info:**
- **Name**: A memorable name (e.g., "Customer Discovery", "Expert Challenge")
- **Description**: What this template is for
- **Default Duration**: Target interview length in minutes

**Content:**
- **Questions**: One question per line. These guide Boswell's conversation.
- **Research Links**: URLs for background context (scraped automatically)

**Style:**
- **Approach**: Select the primary angle
- **Blend with**: Optional secondary angle

## Creating Interviews

When adding an interview to a project, you can either use a template or create a custom one-off configuration.

### Using a Template

1. Go to a project and click "Add Interview"
2. Enter the interviewee's name and email
3. Select a template from the list
4. Optionally add background notes about this specific person
5. Click "Create Interview"

### Using "Other" (Custom Configuration)

1. Select "Other" instead of a template
2. Configure content: questions, research links
3. Configure style: approach and optional blend
4. Optionally check "Save as template for reuse" to save this configuration
5. Add interviewee background
6. Click "Create Interview"

## How It Works

When an interview starts, Boswell's prompt is assembled from:

1. **Base personality**: Warm, curious NPR-style interviewer
2. **Angle instructions**: How to approach the conversation
3. **Content**: Questions and research materials
4. **Person context**: Background on this specific interviewee

The angle instructions modify Boswell's behavior significantly. For example, an Interrogative interview will push back on claims, while a Documentary interview will let the guest lead.

## Architecture

### Data Model

```
InterviewTemplate
├── name, description, default_minutes
├── questions (JSONB)
├── research_summary, research_links
├── angle (enum)
├── angle_secondary (optional)
└── angle_custom (for custom prompts)

Interview
├── template_id (optional - uses template config)
├── questions, research_summary, research_links (override template)
├── angle, angle_secondary, angle_custom (override template)
└── context_notes, context_links (person-specific)
```

### Resolution Logic

Interview values override template values. If an interview has `template_id` set but no `angle`, it uses the template's angle. If the interview has its own `angle`, that takes precedence.

```python
effective_angle = interview.angle or template.angle or "exploratory"
```

## Examples

### Customer Discovery Template

**Content:**
- What challenges are you facing with [topic]?
- Walk me through your current workflow
- What would an ideal solution look like?

**Style:** Exploratory

**Use case:** Understanding customer pain points and workflows

### Expert Challenge Template

**Content:**
- What's your thesis on [topic]?
- What evidence supports that view?
- What would change your mind?

**Style:** Interrogative + Exploratory

**Use case:** Pressure-testing expert opinions, due diligence

### Story Capture Template

**Content:**
- Tell me about your journey with [topic]
- What moments stand out?
- What would you want others to know?

**Style:** Documentary

**Use case:** Capturing testimonials, oral histories, founder stories
