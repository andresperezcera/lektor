import React, { ChangeEvent } from "react";
import { flipSetValue } from "../utils";
import { trans } from "../i18n";
import { WidgetProps } from "./mixins";

function checkboxIsActive(field: string, props: WidgetProps) {
  let value = props.value;
  if (value == null) {
    value = props.placeholder;
    if (value == null) {
      return false;
    }
  }
  for (const item of value) {
    if (item === field) {
      return true;
    }
  }
  return false;
}

export class CheckboxesInputWidget extends React.PureComponent<WidgetProps> {
  static serializeValue(value) {
    return (value || "").join(", ");
  }

  static deserializeValue(value) {
    if (value === "") {
      return null;
    }
    let rv = value.split(",").map((x) => {
      return x.match(/^\s*(.*?)\s*$/)[1];
    });
    if (rv.length === 1 && rv[0] === "") {
      rv = [];
    }
    return rv;
  }

  render() {
    let { disabled, type, onChange } = this.props;

    const onChangeHandler = (
      field: string,
      event: ChangeEvent<HTMLInputElement>
    ) => {
      const newValue = flipSetValue(
        this.props.value,
        field,
        event.target.checked
      );
      onChange(newValue);
    };

    const choices = type.choices.map((item) => (
      <div className="checkbox" key={item[0]}>
        <label>
          <input
            type="checkbox"
            disabled={disabled}
            checked={checkboxIsActive(item[0], this.props)}
            onChange={(e) => onChangeHandler(item[0], e)}
          />
          {trans(item[1])}
        </label>
      </div>
    ));
    return <div className="checkboxes">{choices}</div>;
  }
}
